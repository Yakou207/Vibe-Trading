from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from fintech_quant.backtesting.costs import CostModel
from fintech_quant.backtesting.portfolio import Order, Portfolio, PortfolioSnapshot, Trade
from fintech_quant.risk.rules import RiskGate, RiskLimits
from fintech_quant.trading import TradeAction, TradeDecision


class DailyStrategy(Protocol):
    name: str

    def decide(self, state: dict[str, object]) -> TradeDecision:
        """Return one buy/sell/hold decision for a daily symbol state."""


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 1_000_000.0
    lot_size: int = 100
    max_position_weight: float = 0.1
    max_portfolio_drawdown: float = 0.2
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.001
    slippage_rate: float = 0.0005
    default_order_weight: float = 0.1


@dataclass(frozen=True)
class BacktestMetrics:
    initial_cash: float
    final_equity: float
    total_return: float
    annualized_return: float
    max_drawdown: float
    trade_count: int
    buy_count: int
    sell_count: int
    start_date: str
    end_date: str


@dataclass(frozen=True)
class BacktestResult:
    strategy_name: str
    metrics: BacktestMetrics
    trades: list[Trade]
    equity_curve: list[PortfolioSnapshot]


def run_daily_backtest(
    features: pd.DataFrame,
    strategy: DailyStrategy,
    config: BacktestConfig | None = None,
) -> BacktestResult:
    config = config or BacktestConfig()
    _validate_features(features)
    frame = features.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date.astype(str)
    frame = frame.sort_values(["date", "代码"]).reset_index(drop=True)

    portfolio = Portfolio(
        initial_cash=config.initial_cash,
        cost_model=CostModel(
            commission_rate=config.commission_rate,
            stamp_tax_rate=config.stamp_tax_rate,
            slippage_rate=config.slippage_rate,
        ),
    )
    risk_gate = RiskGate(
        RiskLimits(
            max_position_weight=config.max_position_weight,
            max_portfolio_drawdown=config.max_portfolio_drawdown,
        )
    )

    for date, day_rows in frame.groupby("date", sort=True):
        latest_prices = _latest_prices(day_rows)
        for row in day_rows.to_dict("records"):
            symbol = str(row["代码"])
            price = float(row["close"])
            state = {
                **row,
                "portfolio_cash": portfolio.cash,
                "position_quantity": portfolio.position_quantity(symbol),
            }
            decision = strategy.decide(state)
            if decision.action is TradeAction.BUY:
                quantity = _target_buy_quantity(
                    portfolio,
                    symbol,
                    price,
                    latest_prices,
                    config,
                    target_weight=decision.confidence or config.default_order_weight,
                )
                order = Order(symbol=symbol, date=date, quantity=quantity, price=price)
                if risk_gate.evaluate_buy(portfolio, order, config.lot_size, latest_prices).allowed:
                    portfolio.buy(order, lot_size=config.lot_size)
            elif decision.action is TradeAction.SELL:
                quantity = portfolio.sellable_quantity(symbol)
                order = Order(symbol=symbol, date=date, quantity=quantity, price=price)
                if risk_gate.evaluate_sell(portfolio, order, config.lot_size).allowed:
                    portfolio.sell(order, lot_size=config.lot_size)
        portfolio.record_snapshot(date, latest_prices)
        portfolio.close_trading_day(date)

    return BacktestResult(
        strategy_name=strategy.name,
        metrics=_build_metrics(config.initial_cash, portfolio),
        trades=list(portfolio.trades),
        equity_curve=list(portfolio.snapshots),
    )


def _validate_features(features: pd.DataFrame) -> None:
    if features.empty:
        raise ValueError("Backtest features must not be empty.")
    missing = {"代码", "date", "close"} - set(features.columns)
    if missing:
        raise ValueError(f"Backtest features missing required columns: {sorted(missing)}")


def _latest_prices(day_rows: pd.DataFrame) -> dict[str, float]:
    return {str(row["代码"]): float(row["close"]) for row in day_rows.to_dict("records")}


def _target_buy_quantity(
    portfolio: Portfolio,
    symbol: str,
    price: float,
    latest_prices: dict[str, float],
    config: BacktestConfig,
    target_weight: float,
) -> int:
    if price <= 0 or portfolio.position_quantity(symbol) > 0:
        return 0
    target_value = portfolio.equity(latest_prices) * target_weight
    return int(target_value // price)


def _build_metrics(initial_cash: float, portfolio: Portfolio) -> BacktestMetrics:
    first = portfolio.snapshots[0]
    last = portfolio.snapshots[-1]
    total_return = last.equity / initial_cash - 1
    days = max(1, len(portfolio.snapshots))
    annualized_return = (1 + total_return) ** (252 / days) - 1
    buy_count = sum(1 for trade in portfolio.trades if trade.action is TradeAction.BUY)
    sell_count = sum(1 for trade in portfolio.trades if trade.action is TradeAction.SELL)
    return BacktestMetrics(
        initial_cash=initial_cash,
        final_equity=round(last.equity, 10),
        total_return=round(total_return, 10),
        annualized_return=round(annualized_return, 10),
        max_drawdown=round(portfolio.max_drawdown, 10),
        trade_count=len(portfolio.trades),
        buy_count=buy_count,
        sell_count=sell_count,
        start_date=first.date,
        end_date=last.date,
    )
