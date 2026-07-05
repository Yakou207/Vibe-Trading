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
class DrawdownEpisode:
    start_date: date
    trough_date: date
    recovery_date: date | None
    peak_equity: float
    trough_equity: float
    max_drawdown: float
    duration_days: int
    recovery_days: int | None


@dataclass(frozen=True)
class DrawdownResult:
    points: list[DrawdownPoint]
    max_drawdown: float
    liquidation_date: date | None
    max_drawdown_start: date | None = None
    max_drawdown_end: date | None = None
    recovery_date: date | None = None
    episodes: list[DrawdownEpisode] | None = None
    current_drawdown: float = 0.0
    current_drawdown_start: date | None = None
    current_underwater_days: int = 0


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
    episodes: list[DrawdownEpisode] = []
    active_episode_start: date | None = None
    active_episode_peak_equity: float | None = None
    active_episode_trough_date: date | None = None
    active_episode_trough_equity: float | None = None
    active_episode_max_drawdown = 0.0

    for point in ordered:
        if point.equity > rolling_peak:
            if active_episode_start is not None:
                episodes.append(
                    _episode(
                        start_date=active_episode_start,
                        trough_date=active_episode_trough_date or point.trade_date,
                        recovery_date=point.trade_date,
                        peak_equity=active_episode_peak_equity or rolling_peak,
                        trough_equity=active_episode_trough_equity or point.equity,
                        max_drawdown=active_episode_max_drawdown,
                    )
                )
                active_episode_start = None
                active_episode_peak_equity = None
                active_episode_trough_date = None
                active_episode_trough_equity = None
                active_episode_max_drawdown = 0.0
            rolling_peak = point.equity
            rolling_peak_date = point.trade_date
        drawdown = 0.0 if rolling_peak == 0 else (rolling_peak - point.equity) / rolling_peak
        if drawdown > 0:
            if active_episode_start is None:
                active_episode_start = rolling_peak_date
                active_episode_peak_equity = rolling_peak
                active_episode_trough_date = point.trade_date
                active_episode_trough_equity = point.equity
                active_episode_max_drawdown = drawdown
            elif drawdown > active_episode_max_drawdown:
                active_episode_trough_date = point.trade_date
                active_episode_trough_equity = point.equity
                active_episode_max_drawdown = drawdown
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

    if active_episode_start is not None:
        episodes.append(
            _episode(
                start_date=active_episode_start,
                trough_date=active_episode_trough_date or ordered[-1].trade_date,
                recovery_date=None,
                peak_equity=active_episode_peak_equity or rolling_peak,
                trough_equity=active_episode_trough_equity or ordered[-1].equity,
                max_drawdown=active_episode_max_drawdown,
            )
        )

    last_point = drawdown_points[-1]
    current_drawdown_start = active_episode_start if last_point.drawdown > 0 else None
    return DrawdownResult(
        points=drawdown_points,
        max_drawdown=max_drawdown,
        liquidation_date=liquidation_date,
        max_drawdown_start=max_drawdown_start,
        max_drawdown_end=max_drawdown_end,
        recovery_date=recovery_date,
        episodes=episodes,
        current_drawdown=last_point.drawdown,
        current_drawdown_start=current_drawdown_start,
        current_underwater_days=(
            (last_point.trade_date - current_drawdown_start).days + 1
            if current_drawdown_start is not None
            else 0
        ),
    )


def _episode(
    *,
    start_date: date,
    trough_date: date,
    recovery_date: date | None,
    peak_equity: float,
    trough_equity: float,
    max_drawdown: float,
) -> DrawdownEpisode:
    return DrawdownEpisode(
        start_date=start_date,
        trough_date=trough_date,
        recovery_date=recovery_date,
        peak_equity=peak_equity,
        trough_equity=trough_equity,
        max_drawdown=max_drawdown,
        duration_days=(trough_date - start_date).days + 1,
        recovery_days=(recovery_date - trough_date).days + 1 if recovery_date else None,
    )
