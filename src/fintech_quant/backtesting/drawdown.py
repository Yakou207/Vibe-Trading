from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence


@dataclass(frozen=True)
class EquityPoint:
    trade_date: date
    equity: float


@dataclass(frozen=True)
class DrawdownPoint:
    trade_date: date
    equity: float
    rolling_peak: float
    drawdown: float


@dataclass(frozen=True)
class DrawdownResult:
    points: list[DrawdownPoint]
    max_drawdown: float
    liquidation_date: date | None
    max_drawdown_start: date | None = None
    max_drawdown_end: date | None = None
    recovery_date: date | None = None


def calculate_drawdown(
    points: Sequence[EquityPoint],
    liquidation_threshold: float = 0.15,
) -> DrawdownResult:
    if not points:
        raise ValueError("Equity curve must contain at least one point")

    ordered = sorted(points, key=lambda point: point.trade_date)
    rolling_peak = ordered[0].equity
    rolling_peak_date = ordered[0].trade_date
    max_drawdown = 0.0
    max_drawdown_start: date | None = None
    max_drawdown_end: date | None = None
    max_drawdown_peak_equity: float | None = None
    recovery_date: date | None = None
    liquidation_date: date | None = None
    drawdown_points: list[DrawdownPoint] = []

    for point in ordered:
        if point.equity > rolling_peak:
            rolling_peak = point.equity
            rolling_peak_date = point.trade_date
        drawdown = 0.0 if rolling_peak == 0 else (rolling_peak - point.equity) / rolling_peak
        if liquidation_date is None and drawdown >= liquidation_threshold:
            liquidation_date = point.trade_date
        if drawdown > max_drawdown:
            max_drawdown = drawdown
            max_drawdown_start = rolling_peak_date
            max_drawdown_end = point.trade_date
            max_drawdown_peak_equity = rolling_peak
            recovery_date = None
        if (
            recovery_date is None
            and max_drawdown_end is not None
            and max_drawdown_peak_equity is not None
            and point.trade_date > max_drawdown_end
            and point.equity >= max_drawdown_peak_equity
        ):
            recovery_date = point.trade_date
        drawdown_points.append(
            DrawdownPoint(
                trade_date=point.trade_date,
                equity=point.equity,
                rolling_peak=rolling_peak,
                drawdown=drawdown,
            )
        )

    return DrawdownResult(
        points=drawdown_points,
        max_drawdown=max_drawdown,
        liquidation_date=liquidation_date,
        max_drawdown_start=max_drawdown_start,
        max_drawdown_end=max_drawdown_end,
        recovery_date=recovery_date,
    )
