"""Post-close market pulse and pitfall calendar for the pre-market brief.

Built once per accepted CSI 300 cycle by the scheduled post-close job (research step, after the
shadow pools and the v2 snapshot). Display only: nothing here reaches the counted strategy, the
paper account or the evidence chain.

- Market pulse: six headline indices (Sina daily bars), full-market advancers/decliners and
  limit counts (Legu), Shanghai + Shenzhen turnover (Tencent index quotes), and the share of
  CSI 300 members above MA20/50/250 (local hfq signal prices, no network).
- Pitfall calendar for the current CSI 300 members over the next week: ex-dividend / bonus /
  rights dates from the pipeline's own raw corporate-action run (no network), share unlocks
  (Eastmoney), announced suspensions (Eastmoney) and, in disclosure season, scheduled report
  dates (Eastmoney).

Every provider value is checked against the signal date; a source that fails, times out or
returns another day's data is left out and the block is marked ``partial`` instead of showing
wrong numbers.
"""

from __future__ import annotations

import csv
import importlib
import json
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path

from fintech_quant.data.deadline import call_with_deadline

Fetcher = Callable[..., object]
SOURCE_TIMEOUT = 30.0
EARNINGS_TIMEOUT = 120.0
HORIZON_DAYS = 7
SPARK_SESSIONS = 20
INDICES = (
    ("sh000001", "000001.SH", "上证指数"),
    ("sz399001", "399001.SZ", "深证成指"),
    ("sz399006", "399006.SZ", "创业板指"),
    ("sh000300", "000300.SH", "沪深300"),
    ("sh000905", "000905.SH", "中证500"),
    ("sh000688", "000688.SH", "科创50"),
)
# Whole-market turnover: SSE Composite plus SZSE Composite (深证成指 covers only 500 names).
TURNOVER_CODES = ("sh000001", "sz399106")
# Single-request Tencent batch covering all 6 headline indices plus SSE/SZSE whole-market turnover.
MARKET_PULSE_TENCENT_CODES = tuple(
    dict.fromkeys([code for code, _, _ in INDICES] + list(TURNOVER_CODES))
)
UNLOCK_HIGH_RATIO = 0.05
UNLOCK_MEDIUM_RATIO = 0.01


def default_fetchers() -> dict[str, Fetcher]:
    def ak():
        return importlib.import_module("akshare")

    def records(frame: object) -> list[dict[str, object]]:
        return list(frame.to_dict(orient="records"))  # type: ignore[attr-defined]

    return {
        "index_daily": lambda code: records(ak().stock_zh_index_daily(symbol=code)),
        "activity": lambda: records(ak().stock_market_activity_legu()),
        "tencent": tencent_quotes,
        "unlock": lambda start, end: records(
            ak().stock_restricted_release_detail_em(start_date=start, end_date=end)
        ),
        "suspensions": lambda day: records(ak().stock_tfp_em(date=day)),
        "earnings": lambda period: records(ak().stock_yysj_em(symbol="沪深A股", date=period)),
    }


def tencent_quotes(codes: Sequence[str]) -> dict[str, list[str]]:
    """Raw Tencent quote fields by code (``sh600000`` → ``["1", "浦发银行", ...]``)."""
    import requests

    fields: dict[str, list[str]] = {}
    for start in range(0, len(codes), 60):
        batch = ",".join(codes[start : start + 60])
        response = requests.get(f"https://qt.gtimg.cn/q={batch}", timeout=10)
        response.encoding = "gbk"
        for line in response.text.split(";"):
            name, _, value = line.strip().partition("=")
            if name.startswith("v_") and value.startswith('"'):
                fields[name[2:]] = value.strip('"').split("~")
    return fields


def tencent_code(symbol: str) -> str:
    code, _, exchange = symbol.partition(".")
    return {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(exchange, "sh") + code


def build_market_pulse(
    signal_date: date,
    signal_prices: Path,
    members: Sequence[str],
    turnover_history: Path,
    fetchers: Mapping[str, Fetcher] | None = None,
) -> dict[str, object]:
    fetch = fetchers or default_fetchers()
    day = signal_date.isoformat()
    missing: list[str] = []

    indices = []
    for code, symbol, name in INDICES:
        try:
            rows = _call(fetch["index_daily"], code)
            indices.append(_index_card(rows, symbol, name, day))  # type: ignore[arg-type]
        except Exception as exc:  # one index failing never hides the others
            missing.append(f"index {symbol}: {_reason(exc)}")

    breadth: dict[str, object] = {}
    try:
        breadth.update(_activity(_call(fetch["activity"]), day))  # type: ignore[arg-type]
    except Exception as exc:
        missing.append(f"activity: {_reason(exc)}")
    try:
        turnover = _turnover_bn(_call(fetch["tencent"], list(TURNOVER_CODES)), day)  # type: ignore[arg-type]
        breadth["turnover_cny_bn"] = turnover
        breadth["turnover_vs_5d_pct"] = _record_turnover(turnover_history, day, turnover)
    except Exception as exc:
        missing.append(f"turnover: {_reason(exc)}")
    try:
        breadth.update(csi300_ma_breadth(signal_prices, members, day))
    except Exception as exc:
        missing.append(f"csi300 breadth: {_reason(exc)}")

    if not indices and not breadth:
        return {"status": "unavailable", "missing": missing}
    csi300 = next((i for i in indices if i["symbol"] == "000300.SH"), None)
    regime, note = _regime(csi300, breadth)
    return {
        "status": "partial" if missing else "ok",
        "as_of": day,
        "regime": regime,
        "regime_note": note,
        "indices": indices,
        "breadth": breadth or None,
        "overseas": [],
        "missing": missing,
    }


def build_pitfall_calendar(
    signal_date: date,
    names: Mapping[str, str],
    raw_action_dir: Path,
    fetchers: Mapping[str, Fetcher] | None = None,
    horizon_days: int = HORIZON_DAYS,
) -> dict[str, object]:
    fetch = fetchers or default_fetchers()
    first, last = signal_date + timedelta(days=1), signal_date + timedelta(days=horizon_days)
    alerts: list[dict[str, object]] = []
    missing: list[str] = []

    next_session = next_weekday(signal_date)
    try:
        alerts += corporate_action_alerts(raw_action_dir, names, first, last, next_session)
    except Exception as exc:
        missing.append(f"corporate actions: {_reason(exc)}")
    try:
        rows = _call(fetch["unlock"], first.strftime("%Y%m%d"), last.strftime("%Y%m%d"))
        alerts += _unlock_alerts(rows, names, first, last)  # type: ignore[arg-type]
    except Exception as exc:
        missing.append(f"unlock: {_reason(exc)}")
    for offset in range(1, 4):
        day = signal_date + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        try:
            rows = _call(fetch["suspensions"], day.strftime("%Y%m%d"))
            alerts += _suspension_alerts(rows, names, day)  # type: ignore[arg-type]
        except Exception as exc:
            missing.append(f"suspensions {day}: {_reason(exc)}")
    for period in disclosure_periods(first):
        try:
            rows = _call(fetch["earnings"], period, timeout=EARNINGS_TIMEOUT)
            alerts += _earnings_alerts(rows, names, first, last, next_session)  # type: ignore[arg-type]
        except Exception as exc:
            missing.append(f"earnings {period}: {_reason(exc)}")

    unique = {(a["symbol"], a["kind"], a["date"]): a for a in alerts}
    order = {"high": 0, "medium": 1, "info": 2}
    ranked = sorted(unique.values(), key=lambda a: (order[str(a["severity"])], str(a["date"]), str(a["symbol"])))
    return {
        "status": "partial" if missing else "ok",
        "as_of": signal_date.isoformat(),
        "horizon": [first.isoformat(), last.isoformat()],
        "alerts": ranked,
        "missing": missing,
    }


def csi300_ma_breadth(signal_prices: Path, members: Sequence[str], day: str) -> dict[str, float]:
    wanted = set(members)
    closes: dict[str, list[tuple[str, float]]] = defaultdict(list)
    with signal_prices.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["symbol"] in wanted and row["trade_date"] <= day and row["close"]:
                closes[row["symbol"]].append((row["trade_date"], float(row["close"])))
    above = {20: 0, 50: 0, 250: 0}
    counted = {20: 0, 50: 0, 250: 0}
    for series in closes.values():
        series.sort()
        if series[-1][0] != day:  # suspended today: not counted either way
            continue
        values = [close for _, close in series]
        for window in above:
            if len(values) >= window:
                counted[window] += 1
                above[window] += values[-1] > sum(values[-window:]) / window
    if not counted[20]:
        raise ValueError(f"no CSI 300 member has a {day} close")
    return {
        f"csi300_above_ma{w}_pct": round(above[w] / counted[w], 4) for w in above if counted[w]
    }


def next_weekday(day: date) -> date:
    """The next weekday after ``day`` (exchange holidays are not modelled)."""
    following = day + timedelta(days=1)
    while following.weekday() >= 5:
        following += timedelta(days=1)
    return following


def corporate_action_alerts(
    raw_action_dir: Path, names: Mapping[str, str], first: date, last: date, next_session: date
) -> list[dict[str, object]]:
    alerts = []
    for path in sorted(raw_action_dir.glob("*.jsonl")):
        symbol = path.stem
        if symbol not in names:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("_action_type") == "rights_issue":
                ex = _date(row.get("除权基准日"))
                title = f"配股除权：每 10 股配 {row.get('配股比例')} 股，配股价 {row.get('配股价格')}"
            else:
                if "除权除息日" in row and str(row.get("进度", "实施")).strip() != "实施":
                    continue
                ex = _date(row.get("除权除息日") or row.get("除权日"))
                title = "除权除息：" + _distribution_text(row)
            if ex is None or not first <= ex <= last:
                continue
            alerts.append(
                _alert(symbol, names, "ex_dividend", "medium" if ex == next_session else "info", ex, title,
                       "除权除息日开盘价按除权参考价计算，昨收对比的涨跌幅会失真。")
            )
    return alerts


def disclosure_periods(day: date) -> list[str]:
    """Report periods whose scheduled disclosure dates can fall near ``day``."""
    if day.month <= 4:
        periods = [f"{day.year - 1}1231"]
        return periods + ([f"{day.year}0331"] if day.month == 4 else [])
    if day.month in (7, 8):
        return [f"{day.year}0630"]
    if day.month == 10:
        return [f"{day.year}0930"]
    return []


def _index_card(rows: Sequence[Mapping[str, object]], symbol: str, name: str, day: str) -> dict[str, object]:
    bars = sorted((str(r["date"])[:10], float(r["close"])) for r in rows if r.get("close") is not None)  # type: ignore[arg-type]
    bars = [b for b in bars if b[0] <= day]
    if not bars or bars[-1][0] != day:
        raise ValueError(f"latest bar is {bars[-1][0] if bars else None}, expected {day}")
    closes = [c for _, c in bars]
    close = closes[-1]

    def ma(window: int) -> float | None:
        return None if len(closes) < window else round(sum(closes[-window:]) / window, 2)

    def above(window: int) -> bool | None:
        return None if len(closes) < window else close > sum(closes[-window:]) / window

    return {
        "symbol": symbol,
        "name": name,
        "close": round(close, 2),
        "change_pct": round(close / closes[-2] - 1, 6) if len(closes) > 1 else None,
        "sparkline": [round(c, 2) for c in closes[-SPARK_SESSIONS:]],
        "above_ma20": above(20),
        "above_ma50": above(50),
        "above_ma250": above(250),
        "ma20": ma(20),
        "ma50": ma(50),
        "ma250": ma(250),
    }


def parse_legu_activity(
    rows: Sequence[Mapping[str, object]], expected_day: str | None = None
) -> tuple[str, str | None, dict[str, object]]:
    """Parse Legu full-market activity rows into ``(iso_date, hhmm_or_none, breadth_dict)``."""
    values = {str(r.get("item")).strip(): r.get("value") for r in rows}
    raw_stamp = str(values.get("统计日期", "")).strip()
    stamp = raw_stamp[:10]
    if expected_day is not None:
        if stamp != expected_day:
            raise ValueError(f"activity is for {stamp or 'unknown date'}, expected {expected_day}")
    elif _date(stamp) is None:
        raise ValueError(f"activity has invalid date: {stamp or 'unknown date'}")
    hm = raw_stamp[11:16] if len(raw_stamp) >= 16 and raw_stamp[13:14] == ":" else None
    return (
        stamp,
        hm,
        {
            "advancers": int(float(values["上涨"])),  # type: ignore[arg-type]
            "decliners": int(float(values["下跌"])),  # type: ignore[arg-type]
            "unchanged": int(float(values["平盘"])),  # type: ignore[arg-type]
            "limit_up_count": int(float(values["涨停"])),  # type: ignore[arg-type]
            "limit_down_count": int(float(values["跌停"])),  # type: ignore[arg-type]
        },
    )


def _activity(rows: Sequence[Mapping[str, object]], day: str) -> dict[str, object]:
    return parse_legu_activity(rows, expected_day=day)[2]


def _tencent_iso_date(fields: Sequence[str]) -> str | None:
    if len(fields) <= 30:
        return None
    raw = str(fields[30])[:8]
    if len(raw) != 8 or not raw.isdigit():
        return None
    iso = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return iso if _date(iso) is not None else None


def parse_tencent_turnover_bn(
    quotes: Mapping[str, Sequence[str]], expected_day: str | None = None
) -> tuple[str, float]:
    """Parse SSE + SZSE total turnover (billion CNY) from Tencent quotes."""
    total = 0.0
    seen_day: str | None = None
    for code in TURNOVER_CODES:
        fields = quotes[code]
        raw_day = str(fields[30])[:8] if len(fields) > 30 else ""
        if expected_day is not None:
            if raw_day != expected_day.replace("-", ""):
                raise ValueError(f"{code} quote is for {raw_day}, expected {expected_day}")
            seen_day = expected_day
        else:
            qday = _tencent_iso_date(fields)
            if qday is None:
                raise ValueError(f"{code} quote has invalid date: {raw_day or 'empty'}")
            if seen_day is not None and qday != seen_day:
                raise ValueError(f"{code} quote date {qday} does not match {seen_day}")
            seen_day = qday
        total += float(fields[37]) * 1e4  # 成交额 in 万元
    return seen_day or "", round(total / 1e9, 1)


def parse_tencent_indices(
    quotes: Mapping[str, Sequence[str]],
) -> tuple[str | None, str | None, list[dict[str, object]]]:
    """Parse the six headline A-share indices from Tencent quotes.

    Returns ``(latest_iso_date, latest_hhmm, index_rows)``.
    """
    parsed: list[tuple[str, str | None, dict[str, object]]] = []
    for code, symbol, name in INDICES:
        fields = quotes.get(code)
        if not fields or len(fields) <= 30:
            continue
        qday = _tencent_iso_date(fields)
        price = _float(fields[3])
        prev = _float(fields[4])
        if qday is None or not price or price <= 0 or not prev or prev <= 0:
            continue
        stamp = str(fields[30])
        qtime = (
            f"{stamp[8:10]}:{stamp[10:12]}"
            if len(stamp) >= 12 and stamp[8:12].isdigit()
            else None
        )
        parsed.append(
            (
                qday,
                qtime,
                {
                    "symbol": symbol,
                    "name": name,
                    "close": round(price, 2),
                    "change_pct": round(price / prev - 1, 6),
                },
            )
        )
    if not parsed:
        return None, None, []
    latest_day = max(day for day, _, _ in parsed)
    on_day = [(hm, row) for day, hm, row in parsed if day == latest_day]
    times = [hm for hm, _ in on_day if hm is not None]
    return latest_day, (max(times) if times else None), [row for _, row in on_day]


def _turnover_bn(quotes: Mapping[str, Sequence[str]], day: str) -> float:
    return parse_tencent_turnover_bn(quotes, expected_day=day)[1]


def _record_turnover(path: Path, day: str, turnover_bn: float) -> float | None:
    """Keep a local daily turnover history; return today vs the previous five sessions."""
    history: dict[str, float] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    history[day] = turnover_bn
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(history.items())), indent=1) + "\n", encoding="utf-8")
    previous = [v for d, v in sorted(history.items()) if d < day][-5:]
    if len(previous) < 5:
        return None
    return round(turnover_bn / (sum(previous) / 5) - 1, 4)


def classify_regime(csi300: Mapping[str, object] | None, breadth: Mapping[str, object]) -> tuple[str, str]:
    parts = []
    if csi300 is not None:
        for window in (20, 50, 250):
            flag = csi300.get(f"above_ma{window}")
            if flag is not None:
                parts.append(f"MA{window} {'上方' if flag else '下方'}")
    adv, dec = breadth.get("advancers"), breadth.get("decliners")
    note = "沪深300 " + " · ".join(parts) if parts else ""
    if adv is not None and dec is not None:
        note += f"；上涨 {adv} / 下跌 {dec}"
    if breadth.get("turnover_cny_bn") is not None:
        note += f"；两市成交 {float(breadth['turnover_cny_bn']) / 1000:.2f} 万亿"  # type: ignore[arg-type]
    if csi300 is None or adv is None or dec is None:
        return "unknown", note.lstrip("；")
    ma20, ma50 = csi300.get("above_ma20"), csi300.get("above_ma50")
    if ma20 and ma50 and adv > dec:  # type: ignore[operator]
        return "risk_on", note
    if ma20 is False and ma50 is False and dec > adv:  # type: ignore[operator]
        return "risk_off", note
    return "neutral", note


_regime = classify_regime


def _unlock_alerts(rows: Sequence[Mapping[str, object]], names: Mapping[str, str], first: date, last: date) -> list[dict[str, object]]:
    alerts = []
    for row in rows:
        symbol = _symbol(row.get("股票代码"), names)
        day = _date(row.get("解禁时间"))
        if symbol is None or day is None or not first <= day <= last:
            continue
        ratio = _float(row.get("占解禁前流通市值比例"))
        severity = "info"
        if ratio is not None and ratio >= UNLOCK_HIGH_RATIO:
            severity = "high"
        elif ratio is not None and ratio >= UNLOCK_MEDIUM_RATIO:
            severity = "medium"
        share = f"，占解禁前流通市值 {ratio:.2%}" if ratio is not None else ""
        alerts.append(_alert(symbol, names, "unlock", severity, day,
                             f"限售解禁：{row.get('限售股类型') or '限售股'}", f"实际解禁 {_wan(row.get('实际解禁数量'))} 股{share}。"))
    return alerts


def _suspension_alerts(rows: Sequence[Mapping[str, object]], names: Mapping[str, str], day: date) -> list[dict[str, object]]:
    alerts = []
    for row in rows:
        symbol = _symbol(row.get("代码"), names)
        start = _date(row.get("停牌时间"))
        if symbol is None or start is None or start > day:
            continue
        resume = str(row.get("预计复牌时间") or "").strip()[:10]
        detail = f"停牌原因：{row.get('停牌原因') or '未披露'}；{row.get('停牌期限') or ''}" + (f"，预计 {resume} 复牌" if resume and resume != "NaT" else "")
        alerts.append(_alert(symbol, names, "suspension", "high", day, "停牌", detail.rstrip("；") + "。"))
    return alerts


def _earnings_alerts(
    rows: Sequence[Mapping[str, object]], names: Mapping[str, str], first: date, last: date, next_session: date
) -> list[dict[str, object]]:
    alerts = []
    for row in rows:
        symbol = _symbol(row.get("股票代码"), names)
        disclosed = _date(row.get("实际披露时间"))
        if symbol is None or (disclosed is not None and disclosed < first):
            continue
        scheduled = [_date(row.get(k)) for k in ("三次变更日期", "二次变更日期", "一次变更日期", "首次预约时间")]
        day = next((d for d in scheduled if d is not None), None)
        if day is None or not first <= day <= last:
            continue
        alerts.append(_alert(symbol, names, "earnings", "medium" if day == next_session else "info", day,
                             "定期报告预约披露", "财报披露前后波动通常放大，竞价跳空可能偏大。"))
    return alerts


def _alert(symbol: str, names: Mapping[str, str], kind: str, severity: str, day: date, title: str, detail: str) -> dict[str, object]:
    return {"symbol": symbol, "name": names.get(symbol, ""), "kind": kind, "severity": severity,
            "date": day.isoformat(), "title": title, "detail": detail}


def _distribution_text(row: Mapping[str, object]) -> str:
    parts = []
    for key, label in (("送股", "送"), ("转增", "转增")):
        value = _float(row.get(key))
        if value:
            parts.append(f"每 10 股{label} {value:g} 股")
    cash = _float(row.get("派息"))
    if cash:
        parts.append(f"每 10 股派 {cash:g} 元")
    return "，".join(parts) or "分配方案"


def _symbol(code: object, names: Mapping[str, str]) -> str | None:
    text = str(code or "").strip().zfill(6)
    for suffix in (".SH", ".SZ", ".BJ"):
        if text + suffix in names:
            return text + suffix
    return None


def _date(value: object) -> date | None:
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _float(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _wan(value: object) -> str:
    number = _float(value)
    if number is None:
        return "—"
    return f"{number / 1e4:,.1f} 万" if number >= 1e4 else f"{number:,.0f}"


def _call(fetcher: Fetcher, *args: object, timeout: float = SOURCE_TIMEOUT) -> object:
    return call_with_deadline(timeout, fetcher, *args)


def _reason(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:120]}"
