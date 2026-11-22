"""Morning, on-demand pre-market data for `/picks`: overseas close, overnight notices, 09:25 auction.

The trading desk fetches these when someone opens `/picks`; there is no extra scheduled job.
Display and research only: nothing reaches the counted strategy or the paper account.

Cache rules (Shanghai time):

- Overseas quotes and overnight notices are cached per segment: before 06:00 (US markets may
  still be open, A-share notices still arriving) a fetch is kept for ten minutes only; from 06:00
  and again from 09:25 the first fetch is kept for the rest of that segment. A fetch made the
  previous evening is therefore never reused as the next morning's data. ``refresh`` drops both.
- The auction is fixed once per trading day. Between 09:25 and 09:30 the live price is the
  auction price and the turnover is the auction turnover. After 09:30, with nothing captured yet,
  the gap uses the day's open price and the auction turnover is left empty: intraday cumulative
  turnover would overstate the auction volume ratio many times over.
"""

from __future__ import annotations

import importlib
import json
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

from fintech_quant.data.deadline import call_with_deadline
from fintech_quant.information.event_nlp import tag_text
from fintech_quant.information.premarket_data import tencent_code, tencent_quotes
from fintech_quant.reports.premarket_brief import evaluate_auction, limit_prices, price_limit_rate

SHANGHAI = ZoneInfo("Asia/Shanghai")
MORNING_START = dtime(6, 0)
AUCTION_START = dtime(9, 25)
OPEN_START = dtime(9, 30)
NIGHT_TTL_SECONDS = 600
AUCTION_RETRY_SECONDS = 60
NOTICE_TIMEOUT = 15.0
NOTICE_WORKERS = 4
MAX_NOTICE_SYMBOLS = 60
HIGH_NEGATIVE_WEIGHT = -0.9
BENCHMARK = "sh000300"
# (Sina code, symbol, display name); one request covers all of them.
OVERSEAS = (
    ("hf_CHA50CFD", "FTSE.A50", "富时A50"),
    ("gb_$ixic", "NDX", "纳斯达克"),
    ("gb_$inx", "SPX", "标普500"),
    ("gb_$hxc", "HXC", "纳斯达克金龙"),
    ("fx_susdcnh", "USDCNH", "离岸人民币"),
)

Fetcher = Callable[..., object]
Clock = Callable[[], datetime]


def default_fetchers() -> dict[str, Fetcher]:
    def ak():
        return importlib.import_module("akshare")

    def notices(code: str, begin: str, end: str) -> list[dict[str, object]]:
        try:
            frame = ak().stock_individual_notice_report(
                security=code, symbol="全部", begin_date=begin, end_date=end
            )
        except KeyError as exc:  # akshare's answer for "no notices in this range"
            if exc.args == ("代码",):
                return []
            raise
        return list(frame.to_dict(orient="records"))

    return {"sina": sina_quotes, "tencent": tencent_quotes, "notices": notices}


def sina_quotes(codes: Sequence[str]) -> dict[str, list[str]]:
    import requests

    response = requests.get(
        f"https://hq.sinajs.cn/list={','.join(codes)}",
        headers={"Referer": "https://finance.sina.com.cn"},
        timeout=10,
    )
    response.encoding = "gbk"
    fields: dict[str, list[str]] = {}
    for line in response.text.splitlines():
        name, _, value = line.removeprefix("var hq_str_").partition("=")
        value = value.strip().rstrip(";").strip('"')
        if value:
            fields[name] = value.split(",")
    return fields


def segment(now: datetime) -> str:
    clock = now.time()
    if clock < MORNING_START:
        return "night"
    return "pre_open" if clock < AUCTION_START else "open"


def parse_overseas(raw: Mapping[str, Sequence[str]]) -> list[dict[str, object]]:
    rows = []
    for code, symbol, name in OVERSEAS:
        fields = raw.get(code)
        if not fields:
            continue
        try:
            if code.startswith("gb_"):
                value, change, stamp = float(fields[1]), float(fields[2]) / 100, fields[3][:16]
            elif code.startswith("hf_"):
                value, previous = float(fields[0]), float(fields[7])
                change, stamp = value / previous - 1, f"{fields[12]} {fields[6][:5]}"
            else:  # fx_
                value, change, stamp = float(fields[8]), float(fields[10]) / 100, f"{fields[17]} {fields[0][:5]}"
        except (IndexError, ValueError, ZeroDivisionError):
            continue
        rows.append({"symbol": symbol, "name": name, "value": value, "change_pct": round(change, 6), "as_of": stamp})
    return rows


def auction_quote(fields: Sequence[str], now: datetime) -> dict[str, object] | None:
    """Price and turnover to judge the open with, or ``None`` if there is nothing to judge yet."""
    stamp = fields[30] if len(fields) > 30 else ""
    if stamp[:8] != now.strftime("%Y%m%d") or now.time() < AUCTION_START:
        return None  # no session today, or before the call auction has matched
    previous = _float(fields[4])
    if now.time() < OPEN_START:
        if stamp[8:12] < "0925":
            return None  # quote not yet updated with the auction match
        price, turnover, mode = _float(fields[3]), _float(fields[37]), "auction"
        turnover = turnover * 1e4 if turnover is not None else None  # 万元 → 元
    else:
        price, turnover, mode = _float(fields[5]), None, "open_fallback"
    if not price or not previous:
        return None  # suspended or no match
    return {"price": price, "previous_close": previous, "auction_turnover": turnover, "mode": mode,
            "limit_up": _float(fields[47]) if len(fields) > 47 else None,
            "limit_down": _float(fields[48]) if len(fields) > 48 else None}


def notice_alert(symbol: str, name: str, row: Mapping[str, object]) -> dict[str, object] | None:
    title = str(row.get("公告标题") or "").strip()
    tags = tag_text(title)
    weight = sum(float(t["weight"]) for t in tags)
    if weight >= 0:
        return None
    return {
        "symbol": symbol,
        "name": name,
        "kind": "overnight_negative",
        "severity": "high" if weight <= HIGH_NEGATIVE_WEIGHT else "medium",
        "date": str(row.get("公告日期") or "")[:10],
        "title": title[:60],
        "detail": "隔夜公告标签：" + "、".join(str(t["tag"]) for t in tags) + "。",
        "url": str(row.get("网址") or ""),
    }


class PremarketLive:
    """Per-desk cache of the morning data; refreshes run in one background thread at a time."""

    def __init__(self, store: Path | None, fetchers: Mapping[str, Fetcher] | None = None,
                 clock: Clock | None = None) -> None:
        self.store = store
        self.fetch = fetchers or default_fetchers()
        self.clock = clock or (lambda: datetime.now(SHANGHAI))
        self.lock = threading.Lock()
        self.worker: threading.Thread | None = None
        self.overseas: dict[str, object] | None = None
        self.notices: dict[str, object] | None = None
        self.auction: dict[str, object] | None = None
        self.auction_tried: datetime | None = None

    def snapshot(self, inputs: Mapping[str, object], refresh: bool = False, wait: bool = False) -> dict[str, object]:
        """Current cached data; starts a background refresh when something is stale."""
        now = self.clock()
        with self.lock:
            if refresh:
                self.overseas = self.notices = None
            stale = self._stale(now, inputs)
            running = self.worker is not None and self.worker.is_alive()
            if stale and not running:
                self.worker = threading.Thread(target=self._refresh, args=(inputs,), daemon=True)
                self.worker.start()
                running = True
            worker = self.worker
        if wait and running and worker is not None:
            worker.join()
            running = False
        with self.lock:
            return {
                "segment": segment(now),
                "refreshing": running,
                "overseas": self.overseas,
                "notices": self.notices,
                "auction": self.auction,
            }

    def _stale(self, now: datetime, inputs: Mapping[str, object]) -> bool:
        key = _cache_key(now)
        today = now.date().isoformat()
        if self.auction is None or self.auction.get("date") != today:
            self.auction = self._load_auction(today)
        auction_due = self._auction_due(now, inputs)
        return (
            _expired(self.overseas, key, now)
            or _expired(self.notices, key, now)
            or self.notices.get("signal_date") != inputs.get("signal_date")  # type: ignore[union-attr]
            or auction_due
        )

    def _refresh(self, inputs: Mapping[str, object]) -> None:
        now = self.clock()
        key = _cache_key(now)
        stamp = now.isoformat(timespec="seconds")
        if _expired(self.overseas, key, now):
            try:
                rows = parse_overseas(call_with_deadline(15, self.fetch["sina"], [c for c, _, _ in OVERSEAS]))  # type: ignore[arg-type]
                overseas = {"key": key, "fetched_at": stamp, "status": "ok" if rows else "unavailable", "items": rows}
            except Exception as exc:
                overseas = {"key": key, "fetched_at": stamp, "status": "unavailable", "items": [], "error": _reason(exc)}
            with self.lock:
                self.overseas = overseas
        if _expired(self.notices, key, now) or self.notices.get("signal_date") != inputs.get("signal_date"):  # type: ignore[union-attr]
            notices = self._fetch_notices(inputs, now)
            notices.update(key=key, fetched_at=stamp)
            with self.lock:
                self.notices = notices
        if self._auction_due(now, inputs):
            auction = self._capture_auction(inputs, now)
            with self.lock:
                self.auction = auction
                self.auction_tried = now

    def _auction_due(self, now: datetime, inputs: Mapping[str, object]) -> bool:
        """After 09:25 until captured; a failed or empty try (no session today, auction not matched
        yet) is retried at most once a minute."""
        if now.time() < AUCTION_START:
            return False
        if self.auction is not None and self.auction.get("signal_date") == inputs.get("signal_date"):
            return False
        tried = self.auction_tried
        return tried is None or tried.date() != now.date() or (now - tried).total_seconds() >= AUCTION_RETRY_SECONDS

    def _fetch_notices(self, inputs: Mapping[str, object], now: datetime) -> dict[str, object]:
        signal_date = str(inputs.get("signal_date") or "")
        symbols = list(inputs.get("notice_symbols") or [])[:MAX_NOTICE_SYMBOLS]  # type: ignore[call-overload]
        names: Mapping[str, str] = inputs.get("names") or {}  # type: ignore[assignment]
        if not signal_date or not symbols:
            return {"signal_date": signal_date, "status": "not_checked", "alerts": [], "checked": 0}
        begin, end = signal_date.replace("-", ""), now.strftime("%Y%m%d")

        def one(symbol: str) -> list[dict[str, object]]:
            rows = call_with_deadline(NOTICE_TIMEOUT, self.fetch["notices"], symbol.split(".")[0], begin, end)
            return [
                alert for row in rows  # type: ignore[attr-defined]
                if str(row.get("公告日期") or "")[:10] >= signal_date
                and (alert := notice_alert(symbol, names.get(symbol, ""), row)) is not None
            ]

        alerts: list[dict[str, object]] = []
        failed = 0
        with ThreadPoolExecutor(NOTICE_WORKERS) as pool:
            for future in [pool.submit(one, s) for s in symbols]:
                try:
                    alerts += future.result()
                except Exception:
                    failed += 1
        status = "ok" if not failed else "partial" if failed < len(symbols) else "unavailable"
        return {"signal_date": signal_date, "status": status, "alerts": alerts,
                "checked": len(symbols) - failed, "failed": failed}

    def _capture_auction(self, inputs: Mapping[str, object], now: datetime) -> dict[str, object] | None:
        brief: Mapping[str, object] | None = inputs.get("brief")  # type: ignore[assignment]
        watch: Sequence[str] = inputs.get("auction_symbols") or []  # type: ignore[assignment]
        if brief is None or not watch:
            return None
        try:
            raw = call_with_deadline(15, self.fetch["tencent"], [tencent_code(s) for s in watch] + [BENCHMARK])
        except Exception:
            return None
        quotes = {s: auction_quote(raw.get(tencent_code(s), []), now) for s in watch}  # type: ignore[union-attr]
        benchmark = auction_quote(raw.get(BENCHMARK, []), now)  # type: ignore[union-attr]
        if benchmark is None:
            return None  # no session today, before 09:25, or the auction has not matched yet
        result = evaluate_auction(
            _auction_brief(brief, quotes, inputs, now.date()),
            [{"symbol": s, "price": q["price"], "auction_turnover": q["auction_turnover"]} for s, q in quotes.items() if q],
            benchmark_gap_pct=round(float(benchmark["price"]) / float(benchmark["previous_close"]) - 1, 6),
        )
        result.update(date=now.date().isoformat(), mode=benchmark["mode"], captured_at=now.isoformat(timespec="seconds"))
        self._save_auction(result)
        return result

    def _load_auction(self, today: str) -> dict[str, object] | None:
        path = self._auction_path(today)
        if path is None or not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _save_auction(self, result: Mapping[str, object]) -> None:
        path = self._auction_path(str(result["date"]))
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    def _auction_path(self, day: str) -> Path | None:
        return None if self.store is None else self.store / day / "auction_live.json"


def _auction_brief(brief: Mapping[str, object], quotes: Mapping[str, Mapping[str, object] | None],
                   inputs: Mapping[str, object], today: date) -> dict[str, object]:
    """The brief's rows plus the watched pool names, priced against today's quoted previous close
    (the exchange's ex-rights reference on an ex-date) and limit prices."""
    names: Mapping[str, str] = inputs.get("names") or {}  # type: ignore[assignment]
    luk: Mapping[str, Mapping[str, object]] = inputs.get("luk_setup") or {}  # type: ignore[assignment]
    avg: Mapping[str, float] = inputs.get("avg_turnover_20d") or {}  # type: ignore[assignment]
    rows: dict[str, dict[str, object]] = {}
    for group in ("targets", "near_miss"):
        for item in brief.get(group, []):  # type: ignore[union-attr]
            rows[str(item["symbol"])] = dict(item)
    for symbol in quotes:
        rows.setdefault(symbol, {"symbol": symbol, "name": names.get(symbol, ""), "category": "watch"})
    for symbol, row in rows.items():
        quote = quotes.get(symbol)
        if quote:
            previous = float(quote["previous_close"])  # type: ignore[arg-type]
            up, down = quote.get("limit_up"), quote.get("limit_down")
            if not up or not down:
                up, down = limit_prices(previous, price_limit_rate(symbol, str(row.get("name", "")), today))
            row.update(previous_close=previous, limit_up=up, limit_down=down)
        if symbol in luk:
            row["luk_setup"] = dict(luk[symbol])
        if symbol in avg:
            row["avg_turnover_20d"] = avg[symbol]
    targets = [r for r in rows.values() if r.get("category") == "target"]
    others = [r for r in rows.values() if r.get("category") != "target"]
    return {**brief, "targets": targets, "near_miss": others}


def _cache_key(now: datetime) -> str:
    return f"{now.date().isoformat()}:{segment(now)}"


def _expired(block: Mapping[str, object] | None, key: str, now: datetime) -> bool:
    if block is None or block.get("key") != key:
        return True
    if key.endswith(":night"):
        fetched = datetime.fromisoformat(str(block["fetched_at"]))
        return now - fetched > timedelta(seconds=NIGHT_TTL_SECONDS)
    return False


def _float(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _reason(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:120]}"

