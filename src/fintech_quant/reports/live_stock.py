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
