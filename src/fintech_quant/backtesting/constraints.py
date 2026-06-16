from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AShareTradingConstraints:
    t_plus_one: bool = True
    price_limit_required: bool = True
    suspension_filter_required: bool = True
    lot_size: int = 100
