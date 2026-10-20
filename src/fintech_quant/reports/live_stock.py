"""On-demand analysis for any A-share outside the local CSI 300 point-in-time panel.

When a searched stock is not a CSI 300 member, its data is fetched at search time and cached
once per stock per day:

- the all-A-share code/name list (AkShare `stock_info_a_code_name`);
- about 14 months of forward-adjusted (qfq) daily bars from Sina, falling back to Tencent;
- valuation (Eastmoney `stock_value_em`: PE TTM, PB) and the Tonghuashun financial abstract.

The same Luk four-step check and multi-factor scoring function then run on that data. Momentum
percentiles are measured against the local CSI 300 cross-section, since a full-market snapshot
is not reliably reachable, and Luk's absolute 30% hurdle is shown alongside. None of this is
point-in-time validated, and none of it enters the counted strategy or the shadow pools.

The 分时 (1-minute) view is separate: `live_intraday` fetches it on every request (Eastmoney,
falling back to Sina) and never writes it anywhere.
"""

from __future__ import annotations

import importlib
import json
import threading
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Mapping, Sequence

from fintech_quant.data.price_volume_flow import materialize_price_volume_flow_proxy
from fintech_quant.data.symbols import normalize_a_share_symbol
from fintech_quant.features.factors import ScoreInput, score_stock
from fintech_quant.features.technical_indicators import enrich_daily_bars
from fintech_quant.information.stock_intel import parse_financial_abstract
from fintech_quant.research.momentum_setup import Bar, SetupConfig, SymbolSeries, analyze_at

HISTORY_DAYS = 430
INTRADAY_TIMEOUT = 12.0
Fetcher = Callable[..., object]


@dataclass
class LiveContext:
    cache_dir: Path | None
    fetchers: Mapping[str, Fetcher] = field(default_factory=dict)
    today: date | None = None
    _shares: dict[str, str] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def day(self) -> date:
        return self.today or date.today()

    def all_shares(self) -> dict[str, str]:
        """{symbol: name} for every listed A-share, cached for the day."""
        with self._lock:  # the startup warm-up and the first search must not both fetch
            if self._shares is None:
                self._shares = _cached(self, "universe", "all_shares", self._fetch_shares)
            return self._shares

    def _fetch_shares(self) -> dict[str, str]:
        rows = _records(self._call("code_name"))
        shares = {}
        for row in rows:
            try:
                shares[normalize_a_share_symbol(str(row["code"]))] = str(row["name"]).replace(
                    " ", ""
                )
            except ValueError:
                continue
        if not shares:
            raise ValueError("all-A-share list is empty")
        return shares

    def _call(self, name: str, **kwargs: object) -> object:
        fetcher = self.fetchers.get(name) or _default_fetcher(name)
        return fetcher(**kwargs)


def resolve_any(context: LiveContext, query: str) -> str | None:
    text = query.strip()
    if not text:
        return None
    shares = context.all_shares()
    code = text.upper().split(".")[0]
    for symbol in shares:
        if symbol.split(".")[0] == code:
            return symbol
    exact = [s for s, name in shares.items() if name == text]
    if exact:
        return exact[0]
    partial = sorted(s for s, name in shares.items() if text in name)
    return partial[0] if partial else None


def live_bars(context: LiveContext, symbol: str) -> tuple[list[Bar], str]:
    def fetch() -> dict[str, object]:
        end = context.day()
        start = end - timedelta(days=HISTORY_DAYS)
        exchange, code = symbol.split(".")[1].lower(), symbol.split(".")[0]
        errors = []
        for source in ("sina", "tencent"):
            try:
                rows = _records(
                    context._call(
                        source,
                        symbol=f"{exchange}{code}",
                        start_date=start.strftime("%Y%m%d"),
                        end_date=end.strftime("%Y%m%d"),
                    )
                )
            except Exception as exc:  # fall through to the next provider
                errors.append(f"{source}: {type(exc).__name__}")
                continue
            if rows:
                return {"source": source, "rows": [_bar_row(row, source) for row in rows]}
        raise ValueError(f"no price history for {symbol} ({'; '.join(errors) or 'empty'})")

    payload = _cached(context, "bars", symbol, fetch)
    bars = [
        Bar(r["trade_date"], r["open"], r["high"], r["low"], r["close"], r["volume"])
        for r in payload["rows"]
    ]
    return sorted(bars, key=lambda b: b.trade_date), str(payload["source"])


def live_fundamentals(context: LiveContext, symbol: str) -> dict[str, object]:
    def fetch() -> dict[str, object]:
        code = symbol.split(".")[0]
        result: dict[str, object] = {
            "pe": None,
            "pb": None,
            "roe": None,
            "growth": None,
            "period": None,
        }
        try:
            valuation = _records(context._call("value", symbol=code))
            latest = max(valuation, key=lambda r: str(r.get("数据日期")))
            result["pe"] = _number(latest.get("PE(TTM)"))
            result["pb"] = _number(latest.get("市净率"))
            result["valuation_date"] = str(latest.get("数据日期"))[:10]
        except Exception as exc:
            result["valuation_error"] = type(exc).__name__
        try:
            periods = parse_financial_abstract(_records(context._call("financials", symbol=code)))
            if periods:
                latest = periods[0]
                months = int(str(latest["period"])[5:7] or 12)
                roe = latest.get("roe")
                result["roe"] = None if roe is None else float(roe) * 12 / months
                result["growth"] = latest.get("revenue_yoy")
                result["period"] = latest["period"]
        except Exception as exc:
            result["financials_error"] = type(exc).__name__
        return result

    return _cached(context, "fundamentals", symbol, fetch)


def reference_momentum(
    item: SymbolSeries,
    reference: Mapping[str, Mapping[str, float]],
    config: SetupConfig = SetupConfig(),
) -> dict[str, float] | None:
    """The stock's own 1/3/6-month returns, ranked against the CSI 300 cross-section."""
    if not item.bars or len(item.bars) <= max(config.momentum_windows):
        return None
    close = item.bars[-1].close
    momentum: dict[str, float] = {}
    for window in config.momentum_windows:
        own = close / item.bars[-1 - window].close - 1.0
        peers = sorted(float(row[f"r{window}"]) for row in reference.values())
        momentum[f"r{window}"] = own
        momentum[f"r{window}_pct"] = bisect_left(peers, own) / len(peers) if peers else 0.0
    momentum["momentum_pct"] = sum(momentum[f"r{w}_pct"] for w in config.momentum_windows) / len(
        config.momentum_windows
    )
    return momentum


def live_score(
    symbol: str,
    bars: Sequence[Bar],
    fundamentals: Mapping[str, object],
    momentum: Mapping[str, float] | None,
) -> dict[str, object]:
    rows = [
        {
            "symbol": symbol,
            "trade_date": b.trade_date,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
        }
        for b in bars
    ]
    features = enrich_daily_bars(rows)[-1]
    flow = materialize_price_volume_flow_proxy(rows, source_fetched_at="live")
    flow_values = flow[-1].values if flow else {}
    return_1d = features.get("return_1d")
    score = score_stock(
        ScoreInput(
            symbol=symbol,
            pe=_number(fundamentals.get("pe")),
            pb=_number(fundamentals.get("pb")),
            roe=_number(fundamentals.get("roe")),
            growth=_number(fundamentals.get("growth")),
            close_above_ma20=features.get("close_above_ma20"),  # type: ignore[arg-type]
            close_above_ma60=features.get("close_above_ma60"),  # type: ignore[arg-type]
            relative_strength=None if momentum is None else momentum["r21_pct"],
            rsi=_number(features.get("rsi14")),
            macd_positive=features.get("macd_positive"),  # type: ignore[arg-type]
            volume_confirmed=None if return_1d is None else float(return_1d) >= 0,
            flow_proxy_kind=flow_values.get("flow_proxy_kind"),  # type: ignore[arg-type]
            price_volume_flow_signal=_number(flow_values.get("price_volume_flow_signal")),
            price_volume_outflow_days=flow_values.get("price_volume_outflow_days"),  # type: ignore[arg-type]
        )
    )
    return {
        "total": score.total,
        "confidence": score.confidence,
        "components": {
            name: {"score": c.score, "max_score": c.max_score, "reasons": list(c.reasons)}
            for name, c in score.components.items()
        },
        "missing_fields": list(score.missing_fields),
    }


def analyze_live(
    context: LiveContext, symbol: str, reference: Mapping[str, Mapping[str, float]]
) -> dict[str, object]:
    bars, source = live_bars(context, symbol)
    item = SymbolSeries(symbol, bars)
    momentum = reference_momentum(item, reference)
    as_of = bars[-1].trade_date
    analysis = analyze_at(item, as_of, momentum)
    fundamentals = live_fundamentals(context, symbol)
    return {
        "item": item,
        "as_of": as_of,
        "analysis": analysis,
        "score": live_score(symbol, bars, fundamentals, momentum),
        "fundamentals": fundamentals,
        "source": source,
    }


def live_intraday(
    context: LiveContext, symbol: str, timeout: float = INTRADAY_TIMEOUT
) -> dict[str, object]:
    """1-minute bars for the latest session the source returns (today once trading starts).

    Fetched on every call and never written to disk. Display only: nothing here feeds scoring, the
    shadow pools, the counted strategy or the evidence chain.
    """
    exchange, code = symbol.split(".")[1].lower(), symbol.split(".")[0]
    errors = []
    for source, kwargs in (
        ("minute_em", {"symbol": code}),
        ("minute_sina", {"symbol": f"{exchange}{code}"}),
    ):
        try:
            result = _with_timeout(lambda s=source, k=kwargs: context._call(s, **k), timeout)
            rows = [_minute_row(r, source) for r in _records(result)]
        except Exception as exc:  # fall through to the next provider
            errors.append(f"{source}: {type(exc).__name__}")
            continue
        if not rows:
            errors.append(f"{source}: empty")
            continue
        rows.sort(key=lambda r: r["time"])
        session = rows[-1]["time"][:10]
        earlier = [r for r in rows if r["time"][:10] < session]
        today = [r for r in rows if r["time"][:10] == session]
        if source == "minute_sina":  # Sina has no 均价: cumulative amount over cumulative volume
            amount = volume = 0.0
            for r in today:
                amount += r.pop("amount")
                volume += r["volume"]
                r["avg"] = amount / volume if volume else r["price"]
        return {
            "symbol": symbol,
            "date": session,
            "source": source,
            "prev_close": earlier[-1]["price"] if earlier else None,
            "points": today,  # [{time, price, volume (shares), avg}]
        }
    raise ValueError(f"no intraday data for {symbol} ({'; '.join(errors)})")


def intraday_payload(context: LiveContext, query: str) -> dict[str, object]:
    try:
        try:
            shares = context.all_shares()
        except Exception:  # the list is flaky behind the proxy; a plain code still resolves
            shares = {}
            try:
                symbol: str | None = normalize_a_share_symbol(query)
            except ValueError:
                symbol = None
        else:
            symbol = resolve_any(context, query)
        if symbol is None:
            return {"error": f"未找到 A 股：{query}"}
        payload = live_intraday(context, symbol)
        payload["name"] = shares.get(symbol, "")
        return payload
    except Exception as exc:  # provider outages are reported, not raised
        return {"error": f"分时数据获取失败：{type(exc).__name__}: {str(exc)[:200]}"}


def _minute_row(row: Mapping[str, object], source: str) -> dict[str, object]:
    if source == "minute_em":  # Eastmoney reports volume in lots
        return {
            "time": str(row["时间"])[:16],
            "price": float(row["收盘"]),  # type: ignore[arg-type]
            "volume": float(row["成交量"]) * 100.0,  # type: ignore[arg-type]
            "avg": float(row["均价"]),  # type: ignore[arg-type]
        }
    return {
        "time": str(row["day"])[:16],
        "price": float(row["close"]),  # type: ignore[arg-type]
        "volume": float(row["volume"]),  # type: ignore[arg-type]
        "amount": float(row["amount"]),  # type: ignore[arg-type]
    }


def _with_timeout(fn: Callable[[], object], seconds: float) -> object:
    """Run fn in a daemon thread so a hung provider cannot block the request past `seconds`."""
    result: dict[str, object] = {}

    def run() -> None:
        try:
            result["value"] = fn()
        except BaseException as exc:  # re-raised in the caller's thread
            result["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        raise TimeoutError(f"no response within {seconds:g}s")
    if "error" in result:
        raise result["error"]  # type: ignore[misc]
    return result.get("value")


def _cached(context: LiveContext, kind: str, key: str, fetch: Callable[[], object]):
    path = None
    if context.cache_dir is not None:
        path = context.cache_dir / context.day().isoformat() / kind / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    value = fetch()
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return value


def _default_fetcher(name: str) -> Fetcher:
    def ak():
        return importlib.import_module("akshare")

    return {
        "code_name": lambda: ak().stock_info_a_code_name(),
        "sina": lambda **kw: ak().stock_zh_a_daily(adjust="qfq", **kw),
        "tencent": lambda **kw: ak().stock_zh_a_hist_tx(adjust="qfq", timeout=30, **kw),
        "value": lambda **kw: ak().stock_value_em(**kw),
        "financials": lambda **kw: ak().stock_financial_abstract_ths(indicator="按报告期", **kw),
        "minute_em": lambda **kw: ak().stock_zh_a_hist_min_em(period="1", adjust="", **kw),
        "minute_sina": lambda **kw: ak().stock_zh_a_minute(period="1", adjust="", **kw),
    }[name]


def _bar_row(row: Mapping[str, object], source: str) -> dict[str, object]:
    close = float(row["close"])  # type: ignore[arg-type]
    if source == "tencent":  # Tencent reports volume in lots under "amount"
        volume = float(row["amount"]) * 100.0  # type: ignore[arg-type]
    else:
        volume = float(row["volume"])  # type: ignore[arg-type]
    return {
        "trade_date": str(row["date"])[:10],
        "open": float(row["open"]),  # type: ignore[arg-type]
        "high": float(row["high"]),  # type: ignore[arg-type]
        "low": float(row["low"]),  # type: ignore[arg-type]
        "close": close,
        "volume": volume,
    }


def _records(result: object) -> list[dict[str, object]]:
    if result is None:
        return []
    if hasattr(result, "to_dict"):
        return list(result.to_dict(orient="records"))  # type: ignore[call-arg]
    return [dict(r) for r in result]  # type: ignore[union-attr]


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if number != number else number
