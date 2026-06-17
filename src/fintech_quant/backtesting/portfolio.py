from __future__ import annotations

from dataclasses import dataclass, field

from fintech_quant.backtesting.costs import CostModel
from fintech_quant.trading import TradeAction


@dataclass(frozen=True)
class Order:
    symbol: str
    date: str
    quantity: int
    price: float


@dataclass(frozen=True)
class Trade:
    symbol: str
    date: str
    action: TradeAction
    quantity: int
    price: float
    cash_delta: float


@dataclass
class Position:
    quantity: int = 0
    sellable_quantity: int = 0
    pending_sellable: int = 0


@dataclass(frozen=True)
class PortfolioSnapshot:
    date: str
    cash: float
    market_value: float
    equity: float
    drawdown: float


@dataclass
class Portfolio:
    initial_cash: float
    cost_model: CostModel = field(default_factory=CostModel)
    cash: float = field(init=False)
    positions: dict[str, Position] = field(default_factory=dict)
    trades: list[Trade] = field(default_factory=list)
    snapshots: list[PortfolioSnapshot] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cash = float(self.initial_cash)

    def buy(self, order: Order, lot_size: int = 100) -> Trade | None:
        quantity = _round_to_lot(order.quantity, lot_size)
        if quantity <= 0 or order.price <= 0:
            return None
        cash_delta = self.cost_model.buy_cash_delta(quantity, order.price)
        if self.cash + cash_delta < -1e-9:
            return None
        self.cash += cash_delta
        position = self.positions.setdefault(order.symbol, Position())
        position.quantity += quantity
        position.pending_sellable += quantity
        trade = Trade(order.symbol, order.date, TradeAction.BUY, quantity, order.price, cash_delta)
        self.trades.append(trade)
        return trade

    def sell(self, order: Order, lot_size: int = 100) -> Trade | None:
        position = self.positions.get(order.symbol)
        if position is None or order.price <= 0:
            return None
        quantity = min(_round_to_lot(order.quantity, lot_size), position.sellable_quantity)
        if quantity <= 0:
            return None
        cash_delta = self.cost_model.sell_cash_delta(quantity, order.price)
        self.cash += cash_delta
        position.quantity -= quantity
        position.sellable_quantity -= quantity
        if position.quantity == 0:
            self.positions.pop(order.symbol, None)
        trade = Trade(order.symbol, order.date, TradeAction.SELL, quantity, order.price, cash_delta)
        self.trades.append(trade)
        return trade

    def close_trading_day(self, date: str) -> None:
        for position in self.positions.values():
            position.sellable_quantity += position.pending_sellable
            position.pending_sellable = 0

    def position_quantity(self, symbol: str) -> int:
        position = self.positions.get(symbol)
        return 0 if position is None else position.quantity

    def sellable_quantity(self, symbol: str) -> int:
        position = self.positions.get(symbol)
        return 0 if position is None else position.sellable_quantity

    def market_value(self, latest_prices: dict[str, float]) -> float:
        return sum(
            position.quantity * latest_prices.get(symbol, 0.0)
            for symbol, position in self.positions.items()
        )

    def equity(self, latest_prices: dict[str, float]) -> float:
        return self.cash + self.market_value(latest_prices)

    def record_snapshot(
        self,
        date: str,
        latest_prices: dict[str, float],
        external_equity: float | None = None,
    ) -> PortfolioSnapshot:
        market_value = self.market_value(latest_prices)
        equity = self.equity(latest_prices) if external_equity is None else external_equity
        prior_peak = max((snapshot.equity for snapshot in self.snapshots), default=self.initial_cash)
        peak = max(prior_peak, equity)
        drawdown = 0.0 if peak == 0 else equity / peak - 1
        snapshot = PortfolioSnapshot(date, self.cash, market_value, equity, drawdown)
        self.snapshots.append(snapshot)
        return snapshot

    @property
    def max_drawdown(self) -> float:
        return min((snapshot.drawdown for snapshot in self.snapshots), default=0.0)


def _round_to_lot(quantity: int, lot_size: int) -> int:
    if lot_size <= 0:
        return max(0, int(quantity))
    return max(0, int(quantity) // lot_size * lot_size)
