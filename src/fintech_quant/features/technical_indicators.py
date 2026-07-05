from __future__ import annotations

from collections import defaultdict
from math import sqrt
from statistics import mean
from typing import Mapping, Sequence


def enrich_daily_bars(
    rows: Sequence[Mapping[str, object]],
    *,
    ma_windows: tuple[int, ...] = (20, 60, 250),
    rsi_period: int = 14,
    volatility_window: int = 20,
    relative_strength_window: int = 20,
) -> list[dict[str, object]]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["symbol"])].append(row)

    enriched: list[dict[str, object]] = []
    for symbol in sorted(grouped):
        enriched.extend(
            _enrich_symbol_rows(
                sorted(grouped[symbol], key=lambda row: str(row["trade_date"])),
                ma_windows=ma_windows,
                rsi_period=rsi_period,
                volatility_window=volatility_window,
                relative_strength_window=relative_strength_window,
            )
        )
    return _add_relative_strength_ranks(enriched, relative_strength_window)


def _enrich_symbol_rows(
    rows: list[Mapping[str, object]],
    *,
    ma_windows: tuple[int, ...],
    rsi_period: int,
    volatility_window: int,
    relative_strength_window: int,
) -> list[dict[str, object]]:
    closes: list[float] = []
    returns: list[float] = []
    ema12: float | None = None
    ema26: float | None = None
    signal: float | None = None
    limit_up_streak = 0
    has_limit_up_source = False
    result: list[dict[str, object]] = []

    for row in rows:
        close = float(row["close"])
        previous_close = closes[-1] if closes else None
        return_1d = None if previous_close is None else (close / previous_close) - 1.0
        if return_1d is not None:
            returns.append(return_1d)
        closes.append(close)

        ema12 = _ema(close, ema12, 12)
        ema26 = _ema(close, ema26, 26)
        macd_line = ema12 - ema26
        signal = _ema(macd_line, signal, 9)
        macd_hist = macd_line - signal

        enriched = dict(row)
        enriched["return_1d"] = _round_or_none(return_1d)
        return_window = _window_return(closes, relative_strength_window)
        enriched[f"return_{relative_strength_window}d"] = _round_or_none(return_window)
        for window in ma_windows:
            ma_value = mean(closes[-window:]) if len(closes) >= window else None
            enriched[f"ma{window}"] = _round_or_none(ma_value)
            enriched[f"close_above_ma{window}"] = None if ma_value is None else close > ma_value

        rsi = _rolling_rsi(returns, rsi_period)
        volatility = _rolling_volatility(returns, volatility_window)
        has_limit_up_source = "limit_up" in row
        if has_limit_up_source:
            limit_up_streak = limit_up_streak + 1 if _truthy(row.get("limit_up")) else 0
        else:
            limit_up_streak = 0
        enriched[f"rsi{rsi_period}"] = _round_or_none(rsi)
        enriched["macd_line"] = round(macd_line, 6)
        enriched["macd_signal"] = round(signal, 6)
        enriched["macd_hist"] = round(macd_hist, 6)
        enriched["macd_positive"] = macd_line > signal
        enriched[f"volatility{volatility_window}"] = _round_or_none(volatility)
        enriched["limit_up_streak"] = limit_up_streak if has_limit_up_source else None
        result.append(enriched)

    return result


def _add_relative_strength_ranks(rows: list[dict[str, object]], window: int) -> list[dict[str, object]]:
    grouped_by_date: dict[str, list[dict[str, object]]] = defaultdict(list)
    return_field = f"return_{window}d"
    rank_field = f"rs_rank_{window}d"
    for row in rows:
        row[rank_field] = None
        grouped_by_date[str(row["trade_date"])].append(row)
    for date_rows in grouped_by_date.values():
        ranked_rows = [row for row in date_rows if row.get(return_field) is not None]
        if len(ranked_rows) < 2:
            continue
        ranked_rows.sort(key=lambda row: (float(row[return_field]), str(row["symbol"])))
        denominator = len(ranked_rows) - 1
        for index, row in enumerate(ranked_rows):
            row[rank_field] = round(index / denominator, 6)
    return rows


def _window_return(closes: list[float], window: int) -> float | None:
    if window <= 0:
        raise ValueError("relative_strength_window must be positive")
    if len(closes) <= window:
        return None
    base = closes[-window - 1]
    if base <= 0:
        return None
    return (closes[-1] / base) - 1.0


def _ema(value: float, previous: float | None, span: int) -> float:
    if previous is None:
        return value
    alpha = 2.0 / (span + 1.0)
    return alpha * value + (1.0 - alpha) * previous


def _rolling_rsi(returns: list[float], period: int) -> float | None:
    if len(returns) < period:
        return None
    recent = returns[-period:]
    gains = [max(value, 0.0) for value in recent]
    losses = [abs(min(value, 0.0)) for value in recent]
    average_gain = mean(gains)
    average_loss = mean(losses)
    if average_gain == 0 and average_loss == 0:
        return 50.0
    if average_loss == 0:
        return 100.0
    relative_strength = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def _rolling_volatility(returns: list[float], window: int) -> float | None:
    if len(returns) < window:
        return None
    recent = returns[-window:]
    average = mean(recent)
    return sqrt(sum((value - average) ** 2 for value in recent) / window)


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes"}
