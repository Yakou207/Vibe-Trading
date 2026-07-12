from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class TradeCost:
    commission: float
    stamp_duty: float

    @property
    def total(self) -> float:
        return round(self.commission + self.stamp_duty, 6)


@dataclass(frozen=True)
class AShareCostModel:
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    include_stamp_duty: bool = True

    def __post_init__(self) -> None:
        for name, value in (
            ("commission_rate", self.commission_rate),
            ("minimum_commission", self.minimum_commission),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a non-negative finite number")

    def buy_cost(self, notional: float, trade_date: date) -> TradeCost:
        del trade_date
        return TradeCost(self._commission(notional), 0.0)

    def sell_cost(self, notional: float, trade_date: date) -> TradeCost:
        stamp_rate = 0.0005 if trade_date >= date(2023, 8, 28) else 0.001
        stamp_duty = notional * stamp_rate if self.include_stamp_duty else 0.0
        return TradeCost(self._commission(notional), round(stamp_duty, 6))

    def _commission(self, notional: float) -> float:
        if notional <= 0:
            return 0.0
        return round(max(self.minimum_commission, notional * self.commission_rate), 6)
