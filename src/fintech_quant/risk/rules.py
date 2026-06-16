from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskLimits:
    max_position_weight: float = 0.1
    max_portfolio_drawdown: float = 0.2
