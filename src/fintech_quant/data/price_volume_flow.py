from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from typing import Mapping, Sequence

from fintech_quant.data.factor_store import CapitalFlowSnapshot
from fintech_quant.data.symbols import normalize_a_share_symbol


PROXY_SOURCE = "derived_price_volume_cmf_obv_v1"
PROXY_KIND = "price_volume_cmf_obv"


def materialize_price_volume_flow_proxy(
    bars: Sequence[Mapping[str, object]],
    *,
    source_fetched_at: str,
    window: int = 20,
) -> list[CapitalFlowSnapshot]:
    """Derive a point-in-time price-volume proxy; this is not actual capital-flow data."""
    if window < 2:
        raise ValueError("price-volume proxy window must be at least 2")

    by_symbol: dict[str, list[tuple[date, float, float, float, float]]] = defaultdict(list)
    for row in bars:
        symbol = normalize_a_share_symbol(str(row["symbol"]))
        trade_date = _date(row["trade_date"])
        high = _finite_float(row["high"], "high")
        low = _finite_float(row["low"], "low")
        close = _finite_float(row["close"], "close")
        volume = _finite_float(row["volume"], "volume")
        if high < low or not low <= close <= high:
            raise ValueError(f"invalid OHLC range for {symbol} on {trade_date.isoformat()}")
        if volume < 0:
            raise ValueError(f"negative volume for {symbol} on {trade_date.isoformat()}")
        by_symbol[symbol].append((trade_date, high, low, close, volume))

    snapshots: list[CapitalFlowSnapshot] = []
    for symbol, symbol_bars in sorted(by_symbol.items()):
        ordered = sorted(symbol_bars)
        if len({row[0] for row in ordered}) != len(ordered):
            raise ValueError(f"duplicate price row for {symbol}")
        money_flow_volumes: list[float] = []
        signed_volumes: list[float] = []
        previous_close: float | None = None
        outflow_streak = 0
        for index, (trade_date, high, low, close, volume) in enumerate(ordered):
            multiplier = 0.0 if high == low else ((close - low) - (high - close)) / (high - low)
            money_flow_volumes.append(multiplier * volume)
            signed_volumes.append(
                0.0
                if previous_close is None or close == previous_close
                else volume if close > previous_close else -volume
            )
            previous_close = close
            if index + 1 < window:
                continue
            start = index + 1 - window
            denominator = sum(row[4] for row in ordered[start : index + 1])
            if denominator <= 0:
                continue
            cmf = sum(money_flow_volumes[start : index + 1]) / denominator
            obv_momentum = sum(signed_volumes[start : index + 1]) / denominator
            signal = (cmf + obv_momentum) / 2.0
            outflow_streak = outflow_streak + 1 if signal <= 0 else 0
            snapshots.append(
                CapitalFlowSnapshot(
                    symbol=symbol,
                    trade_date=trade_date,
                    available_date=trade_date,
                    source=PROXY_SOURCE,
                    source_fetched_at=source_fetched_at,
                    values={
                        "flow_proxy_kind": PROXY_KIND,
                        "flow_proxy_window": window,
                        "price_volume_flow_signal": round(signal, 6),
                        "price_volume_outflow_days": outflow_streak,
                        "cmf": round(cmf, 6),
                        "obv_momentum": round(obv_momentum, 6),
                        "main_net_inflow": None,
                        "main_outflow_days": None,
                        "margin_financing_positive": None,
                    },
                )
            )
    return snapshots


def _date(value: object) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _finite_float(value: object, field: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result
