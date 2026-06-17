from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.001
    slippage_rate: float = 0.0

    def buy_cash_delta(self, quantity: int, price: float) -> float:
        gross = quantity * price * (1 + self.slippage_rate)
        return -(gross + gross * self.commission_rate)

    def sell_cash_delta(self, quantity: int, price: float) -> float:
        gross = quantity * price * (1 - self.slippage_rate)
        return gross - gross * self.commission_rate - gross * self.stamp_tax_rate
