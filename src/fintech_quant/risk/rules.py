from __future__ import annotations

from dataclasses import dataclass

from fintech_quant.backtesting.portfolio import Order, Portfolio


@dataclass(frozen=True)
class RiskLimits:
    max_position_weight: float = 0.1
    max_portfolio_drawdown: float = 0.2


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class RiskGate:
    limits: RiskLimits

    def evaluate_buy(
        self,
        portfolio: Portfolio,
        order: Order,
        lot_size: int,
        latest_prices: dict[str, float],
    ) -> RiskDecision:
        if portfolio.max_drawdown <= -self.limits.max_portfolio_drawdown:
            return RiskDecision(False, "Blocked by max drawdown risk limit.")
        quantity = order.quantity // lot_size * lot_size
        if quantity <= 0:
            return RiskDecision(False, "Blocked because order is below lot size.")
        equity = portfolio.equity(latest_prices)
        if equity <= 0:
            return RiskDecision(False, "Blocked because portfolio equity is not positive.")
        current_value = portfolio.position_quantity(order.symbol) * order.price
        proposed_value = current_value + quantity * order.price
        if proposed_value / equity > self.limits.max_position_weight:
            return RiskDecision(False, "Blocked by max position weight risk limit.")
        return RiskDecision(True, "Allowed.")

    def evaluate_sell(
        self,
        portfolio: Portfolio,
        order: Order,
        lot_size: int,
    ) -> RiskDecision:
        quantity = order.quantity // lot_size * lot_size
        if quantity <= 0:
            return RiskDecision(False, "Blocked because order is below lot size.")
        if portfolio.sellable_quantity(order.symbol) <= 0:
            return RiskDecision(False, "Blocked by T+1 sellable share limit.")
        return RiskDecision(True, "Allowed.")
