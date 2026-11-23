"""Morning and intraday on-demand pre-market data for `/picks`: live A-share market temperature,
overseas close, overnight notices, and 09:25 auction.

The trading desk fetches these when someone opens `/picks`; there is no extra scheduled job.
Display and research only: nothing reaches the counted strategy or the paper account, and
``brief.json`` on disk is never mutated.

Cache rules (Shanghai time):

- Live A-share market pulse (6 headline indices + SSE/SZSE turnover via Tencent, full-market
  breadth via Legu) runs on trading weekdays from 09:25 whenever the latest post-close brief has
  not yet covered today:
  - 09:25–15:05: 60s TTL (bypassed on ``refresh=True``), labeled ``intraday_live``.
  - 15:05+: 600s TTL (bypassed on ``refresh=True``), labeled ``today_close_live``.
  - Before 09:25, on weekends, or once today's post-close brief exists: not overlaid.
- Overseas quotes and overnight notices are cached per segment: before 06:00 (US markets may
  still be open, A-share notices still arriving) a fetch is kept for ten minutes only; from 06:00
  and again from 09:25 the first fetch is kept for the rest of that segment. A fetch made the
  previous evening is therefore never reused as the next morning's data. ``refresh`` drops them.
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

from fintech_quant.clock import SHANGHAI
from fintech_quant.data.deadline import call_with_deadline
from fintech_quant.data.net_adaptive import run_parallel_with_deadline
from fintech_quant.information.event_nlp import tag_text
from fintech_quant.information.premarket_data import (
    INDICES,
    MARKET_PULSE_TENCENT_CODES,
    SPARK_SESSIONS,
    classify_regime,
    parse_legu_activity,
    parse_tencent_indices,
    parse_tencent_turnover_bn,
    tencent_code,
    tencent_quotes,
)
from fintech_quant.reports.premarket_brief import evaluate_auction, limit_prices, price_limit_rate

MORNING_START = dtime(6, 0)
AUCTION_START = dtime(9, 25)
OPEN_START = dtime(9, 30)
CLOSE_SETTLE = dtime(15, 5)
NIGHT_TTL_SECONDS = 600
PULSE_INTRADAY_TTL_SECONDS = 60
PULSE_POST_CLOSE_TTL_SECONDS = 600
AUCTION_RETRY_SECONDS = 60
FAST_DEADLINE_SECONDS = 10.0
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

    def activity() -> list[dict[str, object]]:
        return list(ak().stock_market_activity_legu().to_dict(orient="records"))

    return {
        "sina": sina_quotes,
        "tencent": tencent_quotes,
        "activity": activity,
        "notices": notices,
    }


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
        move = sina_move(code, name, raw.get(code))
        if move is not None:
            rows.append({"symbol": symbol, "name": name, "value": move["value"],
                         "change_pct": move["change_pct"], "as_of": move["as_of"]})
    return rows


def sina_move(code: str, label: str, fields: Sequence[str] | None) -> dict[str, object] | None:
    """Last price and change from one Sina quote line: US stock or index, futures, or FX."""
    if not fields:
        return None
    try:
        if code.startswith("gb_"):
            value, change, stamp = float(fields[1]), float(fields[2]) / 100, fields[3][:16]
        elif code.startswith("hf_"):
            value, previous = float(fields[0]), float(fields[7])
            change, stamp = value / previous - 1, f"{fields[12]} {fields[6][:5]}"
        elif code.startswith("fx_"):
            value, change, stamp = float(fields[8]), float(fields[10]) / 100, f"{fields[17]} {fields[0][:5]}"
        else:
            return None
    except (IndexError, ValueError, ZeroDivisionError):
        return None
    return {"code": code, "label": label, "value": value, "change_pct": round(change, 6), "as_of": stamp}


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


def merge_live_market_pulse(
    base_pulse: Mapping[str, object] | None,
    live_pulse: Mapping[str, object] | None,
    *,
    signal_date: str | None = None,
) -> dict[str, object]:
    """Safely overlay live A-share indices, turnover, and breadth onto a post-close pulse in memory.

    Never mutates ``base_pulse`` or ``live_pulse``. Partial live failures keep existing brief
    fields intact; full failure or non-live/stale dates return the post-close snapshot unchanged.
    """
    pulse: dict[str, object] = dict(base_pulse) if base_pulse else {"status": "unavailable"}
    raw_indices = pulse.get("indices")
    indices: list[dict[str, object]] = []
    if isinstance(raw_indices, Sequence) and not isinstance(raw_indices, (str, bytes)):
        for item in raw_indices:
            if isinstance(item, Mapping):
                card = dict(item)
                if isinstance(card.get("sparkline"), list):
                    card["sparkline"] = list(card["sparkline"])  # type: ignore[arg-type]
                indices.append(card)
        pulse["indices"] = indices
    raw_breadth = pulse.get("breadth")
    breadth: dict[str, object] | None = dict(raw_breadth) if isinstance(raw_breadth, Mapping) else None
    if breadth is not None:
        pulse["breadth"] = breadth

    live_date = str(live_pulse.get("live_date") or "") if isinstance(live_pulse, Mapping) else ""
    live_status = str(live_pulse.get("live_status") or "") if isinstance(live_pulse, Mapping) else ""
    live_indices_raw = (live_pulse.get("indices") or []) if isinstance(live_pulse, Mapping) else []
    live_activity = live_pulse.get("activity") if isinstance(live_pulse, Mapping) else None
    live_turnover = live_pulse.get("turnover_cny_bn") if isinstance(live_pulse, Mapping) else None

    has_live = (
        bool(live_date)
        and live_status in ("intraday_live", "today_close_live")
        and (bool(live_indices_raw) or isinstance(live_activity, Mapping) or live_turnover is not None)
    )
    if signal_date and live_date and live_date <= signal_date:
        has_live = False

    if not has_live:
        if pulse.get("status") != "unavailable" and "live_status" not in pulse:
            pulse["live_status"] = "post_close"
        return pulse

    # 1. Overlay live headline indices (preserving sparkline & recomputing MA flags when levels exist)
    live_by_sym: dict[str, Mapping[str, object]] = {
        str(row["symbol"]): row
        for row in live_indices_raw  # type: ignore[union-attr]
        if isinstance(row, Mapping) and row.get("symbol")
    }
    if live_by_sym:
        for card in indices:
            sym = str(card.get("symbol") or "")
            live_idx = live_by_sym.get(sym)
            if live_idx is None:
                continue
            live_close = float(live_idx["close"])  # type: ignore[arg-type]
            card["close"] = live_close
            card["change_pct"] = live_idx.get("change_pct")
            spark = card.get("sparkline")
            if isinstance(spark, list) and spark:
                spark.append(live_close)
                if len(spark) > SPARK_SESSIONS:
                    del spark[:-SPARK_SESSIONS]
            for window in (20, 50, 250):
                ma_level = card.get(f"ma{window}")
                if ma_level is not None:
                    card[f"above_ma{window}"] = live_close > float(ma_level)  # type: ignore[arg-type]
        existing_syms = {str(c.get("symbol")) for c in indices}
        for _, sym, _ in INDICES:
            if sym not in existing_syms and sym in live_by_sym:
                li = live_by_sym[sym]
                indices.append(
                    {
                        "symbol": li["symbol"],
                        "name": li["name"],
                        "close": li["close"],
                        "change_pct": li.get("change_pct"),
                        "sparkline": [],
                        "above_ma20": None,
                        "above_ma50": None,
                        "above_ma250": None,
                    }
                )
        pulse["indices"] = indices

    # 2. Overlay live breadth and turnover (always preserving CSI 300 MA breadth from post-close brief)
    if isinstance(live_activity, Mapping) or live_turnover is not None:
        merged_breadth = dict(breadth or {})
        if isinstance(live_activity, Mapping):
            for key in ("advancers", "decliners", "unchanged", "limit_up_count", "limit_down_count"):
                if key in live_activity:
                    merged_breadth[key] = live_activity[key]
        if live_turnover is not None:
            merged_breadth["turnover_cny_bn"] = live_turnover
            # Post-close 5-day ratio belongs to signal_date's full session, not live turnover.
            merged_breadth.pop("turnover_vs_5d_pct", None)
        pulse["breadth"] = merged_breadth

    # 3. Recompute regime & regime_note from the updated live indices & breadth
    csi300 = next((c for c in indices if c.get("symbol") == "000300.SH"), None)
    effective_breadth = pulse.get("breadth")
    regime, note = classify_regime(
        csi300, effective_breadth if isinstance(effective_breadth, Mapping) else {}
    )
    if regime != "unknown" or not pulse.get("regime"):
        pulse["regime"] = regime
    if note:
        pulse["regime_note"] = note

    pulse["live_status"] = live_status
    pulse["live_date"] = live_date
    pulse["live_as_of"] = live_pulse.get("live_as_of") if isinstance(live_pulse, Mapping) else None
    if pulse.get("status") == "unavailable":
        live_ok = isinstance(live_pulse, Mapping) and live_pulse.get("status") == "ok"
        pulse["status"] = "ok" if live_ok else "partial"
    return pulse


class PremarketLive:
    """Per-desk cache of on-demand pre-market & intraday data with decoupled fast/slow workers."""

    def __init__(self, store: Path | None, fetchers: Mapping[str, Fetcher] | None = None,
                 clock: Clock | None = None) -> None:
        self.store = store
        self.fetch = fetchers or default_fetchers()
        self.clock = clock or (lambda: datetime.now(SHANGHAI))
        self.lock = threading.Lock()
        self.fast_worker: threading.Thread | None = None
        self.notices_worker: threading.Thread | None = None
        self.overseas: dict[str, object] | None = None
        self.market_pulse: dict[str, object] | None = None
        self.notices: dict[str, object] | None = None
        self.auction: dict[str, object] | None = None
        self.auction_tried: datetime | None = None

    def snapshot(
        self,
        inputs: Mapping[str, object],
        refresh: bool = False,
        wait: bool = False,
        *,
        phase: str | None = None,
    ) -> dict[str, object]:
        """Current cached data; runs fast and/or slow notice fetches according to ``phase``.

        - ``phase="fast"``: synchronously refreshes only fast sources (live A-share pulse, overseas,
          auction) under a tight shared deadline, skipping the slow notice scan.
        - ``phase="notices"``: synchronously refreshes only the overnight notice scan.
        - ``phase=None`` (default): backwards-compatible combined behavior (background unless ``wait``).
        """
        now = self.clock()
        with self.lock:
            today = now.date().isoformat()
            if self.auction is None or self.auction.get("date") != today:
                self.auction = self._load_auction(today)
            if refresh:
                if phase == "notices":
                    self.notices = None
                else:
                    self.overseas = self.market_pulse = self.notices = None

            if phase in (None, "fast") and self._fast_due(now, inputs):
                if self.fast_worker is None or not self.fast_worker.is_alive():
                    self.fast_worker = threading.Thread(
                        target=self._refresh_fast, args=(inputs,), daemon=True
                    )
                    self.fast_worker.start()

            if phase in (None, "notices") and self._notices_due(now, inputs):
                if self.notices_worker is None or not self.notices_worker.is_alive():
                    self.notices_worker = threading.Thread(
                        target=self._refresh_notices, args=(inputs,), daemon=True
                    )
                    self.notices_worker.start()

            fast_worker = self.fast_worker
            notices_worker = self.notices_worker

        if phase == "fast":
            if fast_worker is not None and fast_worker.is_alive():
                fast_worker.join()
        elif phase == "notices":
            if notices_worker is not None and notices_worker.is_alive():
                notices_worker.join()
        elif wait:
            if fast_worker is not None and fast_worker.is_alive():
                fast_worker.join()
            if notices_worker is not None and notices_worker.is_alive():
                notices_worker.join()

        with self.lock:
            fast_running = self.fast_worker is not None and self.fast_worker.is_alive()
            notices_running = self.notices_worker is not None and self.notices_worker.is_alive()
            if phase == "fast":
                refreshing = fast_running
            elif phase == "notices":
                refreshing = notices_running
            else:
                refreshing = fast_running or notices_running
            notices_pending = self._has_notice_work(inputs) and (
                notices_running or self._notices_due(now, inputs)
            )
            return {
                "segment": segment(now),
                "refreshing": refreshing,
                "overseas": self.overseas,
                "market_pulse": self.market_pulse,
                "notices": self.notices,
                "auction": self.auction,
                "notices_pending": notices_pending,
            }

    def _market_pulse_enabled(self, inputs: Mapping[str, object]) -> bool:
        brief = inputs.get("brief")
        has_brief_pulse = isinstance(brief, Mapping) and bool(brief.get("market_pulse"))
        return (
            "activity" in self.fetch
            or has_brief_pulse
            or bool(inputs.get("live_market_pulse"))
        )

    def _market_pulse_due(self, now: datetime, inputs: Mapping[str, object]) -> bool:
        if not self._market_pulse_enabled(inputs):
            return False
        if now.weekday() >= 5 or now.time() < AUCTION_START:
            return False
        today = now.date().isoformat()
        signal_date = str(inputs.get("signal_date") or "")
        if signal_date and signal_date >= today:
            return False
        block = self.market_pulse
        if block is None or block.get("date") != today:
            return True
        expected_mode = "intraday_live" if now.time() < CLOSE_SETTLE else "today_close_live"
        if block.get("live_status") != expected_mode and block.get("status") != "unavailable":
            return True
        ttl = (
            PULSE_INTRADAY_TTL_SECONDS
            if now.time() < CLOSE_SETTLE
            else PULSE_POST_CLOSE_TTL_SECONDS
        )
        fetched = datetime.fromisoformat(str(block["fetched_at"]))
        return (now - fetched).total_seconds() >= ttl

    def _fast_due(self, now: datetime, inputs: Mapping[str, object]) -> bool:
        key = _cache_key(now)
        overseas_due = "sina" in self.fetch and _expired(self.overseas, key, now)
        pulse_due = self._market_pulse_due(now, inputs)
        auction_due = self._auction_due(now, inputs)
        return overseas_due or pulse_due or auction_due

    def _has_notice_work(self, inputs: Mapping[str, object]) -> bool:
        return bool(
            "notices" in self.fetch
            and str(inputs.get("signal_date") or "")
            and list(inputs.get("notice_symbols") or [])  # type: ignore[call-overload]
        )

    def _notices_due(self, now: datetime, inputs: Mapping[str, object]) -> bool:
        if "notices" not in self.fetch:
            return False
        key = _cache_key(now)
        if _expired(self.notices, key, now):
            return True
        return self.notices.get("signal_date") != inputs.get("signal_date")  # type: ignore[union-attr]

    def _refresh_fast(self, inputs: Mapping[str, object]) -> None:
        now = self.clock()
        key = _cache_key(now)
        stamp = now.isoformat(timespec="seconds")
        with self.lock:
            overseas_due = "sina" in self.fetch and _expired(self.overseas, key, now)
            pulse_due = self._market_pulse_due(now, inputs)
            auction_due = self._auction_due(now, inputs)

        tasks: dict[str, Callable[[], object]] = {}
        if overseas_due:
            tasks["overseas"] = lambda: self.fetch["sina"]([c for c, _, _ in OVERSEAS])
        if pulse_due:
            if "tencent" in self.fetch:
                tasks["pulse_tencent"] = lambda: self.fetch["tencent"](
                    list(MARKET_PULSE_TENCENT_CODES)
                )
            if "activity" in self.fetch:
                tasks["pulse_activity"] = lambda: self.fetch["activity"]()
        brief: Mapping[str, object] | None = inputs.get("brief")  # type: ignore[assignment]
        watch: Sequence[str] = inputs.get("auction_symbols") or []  # type: ignore[assignment]
        run_auction = auction_due and "tencent" in self.fetch and brief is not None and bool(watch)
        if run_auction:
            tasks["auction"] = lambda: self.fetch["tencent"](
                [tencent_code(s) for s in watch] + [BENCHMARK]
            )

        if not tasks:
            return

        values, errors = run_parallel_with_deadline(
            tasks, FAST_DEADLINE_SECONDS, provider_prefix="premarket_fast"
        )

        if overseas_due:
            if "overseas" in values:
                try:
                    rows = parse_overseas(values["overseas"])  # type: ignore[arg-type]
                    overseas = {
                        "key": key,
                        "fetched_at": stamp,
                        "status": "ok" if rows else "unavailable",
                        "items": rows,
                    }
                except Exception as exc:
                    overseas = {
                        "key": key,
                        "fetched_at": stamp,
                        "status": "unavailable",
                        "items": [],
                        "error": _reason(exc),
                    }
            else:
                exc = errors.get("overseas")
                overseas = {
                    "key": key,
                    "fetched_at": stamp,
                    "status": "unavailable",
                    "items": [],
                    "error": _reason(exc) if exc else "unavailable",
                }
            with self.lock:
                self.overseas = overseas

        if pulse_due:
            pulse_block = self._build_live_pulse(values, errors, now, stamp)
            with self.lock:
                self.market_pulse = pulse_block

        if auction_due:
            auction_result = None
            if run_auction and "auction" in values:
                try:
                    auction_result = self._evaluate_live_auction(
                        values["auction"], brief, watch, inputs, now  # type: ignore[arg-type]
                    )
                except Exception:
                    auction_result = None
            with self.lock:
                self.auction = auction_result
                self.auction_tried = now

    def _build_live_pulse(
        self,
        values: Mapping[str, object],
        errors: Mapping[str, BaseException],
        now: datetime,
        stamp: str,
    ) -> dict[str, object]:
        today = now.date().isoformat()
        pulse_errors: dict[str, str] = {}
        for k in ("pulse_tencent", "pulse_activity"):
            if k in errors:
                pulse_errors[k] = _reason(errors[k])

        indices: list[dict[str, object]] = []
        idx_hm: str | None = None
        turnover_bn: float | None = None
        if "pulse_tencent" in values:
            raw_tq = values["pulse_tencent"]
            try:
                idx_date, parsed_hm, parsed_rows = parse_tencent_indices(raw_tq)  # type: ignore[arg-type]
                if idx_date == today and parsed_rows:
                    indices = parsed_rows
                    idx_hm = parsed_hm
            except Exception as exc:
                pulse_errors["pulse_indices"] = _reason(exc)
            try:
                to_date, parsed_to = parse_tencent_turnover_bn(raw_tq)  # type: ignore[arg-type]
                if to_date == today:
                    turnover_bn = parsed_to
            except Exception as exc:
                pulse_errors["pulse_turnover"] = _reason(exc)

        activity: dict[str, object] | None = None
        act_hm: str | None = None
        if "pulse_activity" in values:
            try:
                act_date, parsed_act_hm, parsed_act = parse_legu_activity(values["pulse_activity"])  # type: ignore[arg-type]
                if act_date == today:
                    activity = parsed_act
                    act_hm = parsed_act_hm
            except Exception as exc:
                pulse_errors["pulse_activity"] = _reason(exc)

        has_any = bool(indices) or turnover_bn is not None or activity is not None
        if not has_any:
            return {
                "date": today,
                "fetched_at": stamp,
                "status": "unavailable",
                "live_status": "post_close",
                "live_date": None,
                "live_as_of": None,
                "indices": [],
                "turnover_cny_bn": None,
                "activity": None,
                "errors": pulse_errors,
            }

        live_status = "intraday_live" if now.time() < CLOSE_SETTLE else "today_close_live"
        full_ok = bool(indices) and turnover_bn is not None and activity is not None
        return {
            "date": today,
            "fetched_at": stamp,
            "status": "ok" if full_ok else "partial",
            "live_status": live_status,
            "live_date": today,
            "live_as_of": idx_hm or act_hm or now.strftime("%H:%M"),
            "indices": indices,
            "turnover_cny_bn": turnover_bn,
            "activity": activity,
            "errors": pulse_errors,
        }

    def _refresh_notices(self, inputs: Mapping[str, object]) -> None:
        now = self.clock()
        key = _cache_key(now)
        stamp = now.isoformat(timespec="seconds")
        notices = self._fetch_notices(inputs, now)
        notices.update(key=key, fetched_at=stamp)
        with self.lock:
            self.notices = notices

    def _auction_due(self, now: datetime, inputs: Mapping[str, object]) -> bool:
        """After 09:25 until captured; a failed or empty try (no session today, auction not matched
        yet) is retried at most once a minute."""
        if now.time() < AUCTION_START:
            return False
        if inputs.get("brief") is None or not inputs.get("auction_symbols"):
            return False
        if str(inputs.get("signal_date") or "") >= now.date().isoformat():
            return False  # the brief's targets trade at the next session, which has not opened yet
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

    def _evaluate_live_auction(
        self,
        raw: Mapping[str, Sequence[str]],
        brief: Mapping[str, object] | None,
        watch: Sequence[str],
        inputs: Mapping[str, object],
        now: datetime,
    ) -> dict[str, object] | None:
        if brief is None or not watch or not isinstance(raw, Mapping):
            return None
        quotes = {s: auction_quote(raw.get(tencent_code(s), []), now) for s in watch}
        benchmark = auction_quote(raw.get(BENCHMARK, []), now)
        if benchmark is None:
            return None  # no session today, before 09:25, or the auction has not matched yet
        result = evaluate_auction(
            _auction_brief(brief, quotes, inputs, now.date()),
            [{"symbol": s, "price": q["price"], "auction_turnover": q["auction_turnover"]} for s, q in quotes.items() if q],
            benchmark_gap_pct=round(float(benchmark["price"]) / float(benchmark["previous_close"]) - 1, 6),  # type: ignore[arg-type]
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
