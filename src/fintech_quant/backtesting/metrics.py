from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean, pstdev
from typing import Any


@dataclass(frozen=True)
class EquityMetrics:
    start_date: str
    end_date: str
    initial_equity: float
    final_equity: float
    total_return: float
    annualized_return: float
    sharpe_ratio: float
    max_drawdown: float
    observations: int


def calculate_equity_metrics(
    equity_curve: list[dict[str, Any]],
    periods_per_year: int = 252,
) -> EquityMetrics:
    if not equity_curve:
        raise ValueError("equity_curve must contain at least one observation")

    equities = [float(row["equity"]) for row in equity_curve]
    if any(value <= 0 for value in equities):
        raise ValueError("equity values must be positive")

    start_date = str(equity_curve[0]["date"])
    end_date = str(equity_curve[-1]["date"])
    initial_equity = equities[0]
    final_equity = equities[-1]
    total_return = final_equity / initial_equity - 1.0

    observations = len(equities)
    if observations > 1:
        annualized_return = (final_equity / initial_equity) ** (
            periods_per_year / (observations - 1)
        ) - 1.0
    else:
        annualized_return = 0.0

    daily_returns = [
        equities[index] / equities[index - 1] - 1.0 for index in range(1, observations)
    ]
    sharpe_ratio = _annualized_sharpe(daily_returns, periods_per_year)
    max_drawdown = _max_drawdown(equities)

    return EquityMetrics(
        start_date=start_date,
        end_date=end_date,
        initial_equity=initial_equity,
        final_equity=final_equity,
        total_return=total_return,
        annualized_return=annualized_return,
        sharpe_ratio=sharpe_ratio,
        max_drawdown=max_drawdown,
        observations=observations,
    )


def _annualized_sharpe(returns: list[float], periods_per_year: int) -> float:
    if not returns:
        return 0.0
    volatility = pstdev(returns)
    if volatility == 0:
        return 0.0
    return mean(returns) / volatility * sqrt(periods_per_year)


def _max_drawdown(equities: list[float]) -> float:
    peak = equities[0]
    worst = 0.0
    for equity in equities:
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)
    return worst
