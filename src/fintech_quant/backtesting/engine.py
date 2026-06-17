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
    execution_price_column: str = "open"
    price_limit_rate: float = 0.20
    price_limit_tolerance: float = 0.002
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
    sharpe_ratio: float
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
    frame["previous_close"] = frame.groupby("代码")["close"].shift(1)

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

    pending_decisions: dict[str, TradeDecision] = {}

    for date, day_rows in frame.groupby("date", sort=True):
        latest_prices = _latest_prices(day_rows)
        execution_prices = _execution_prices(day_rows, config.execution_price_column)
        rows = day_rows.to_dict("records")

        for row in rows:
            symbol = str(row["代码"])
            decision = pending_decisions.pop(symbol, None)
            if decision is None:
                continue
            price = float(row[config.execution_price_column])
            if decision.action is TradeAction.BUY:
                if not _can_buy(row, config):
                    continue
                quantity = _target_buy_quantity(
                    portfolio,
                    symbol,
                    price,
                    execution_prices,
                    config,
                    target_weight=decision.confidence or config.default_order_weight,
                )
                order = Order(symbol=symbol, date=date, quantity=quantity, price=price)
                if risk_gate.evaluate_buy(portfolio, order, config.lot_size, execution_prices).allowed:
                    portfolio.buy(order, lot_size=config.lot_size)
            elif decision.action is TradeAction.SELL:
                if not _can_sell(row, config):
                    continue
                quantity = portfolio.sellable_quantity(symbol)
                order = Order(symbol=symbol, date=date, quantity=quantity, price=price)
                if risk_gate.evaluate_sell(portfolio, order, config.lot_size).allowed:
                    portfolio.sell(order, lot_size=config.lot_size)

        portfolio.record_snapshot(date, latest_prices)
        portfolio.close_trading_day(date)

        for row in day_rows.to_dict("records"):
            symbol = str(row["代码"])
            state = {
                **row,
                "portfolio_cash": portfolio.cash,
                "position_quantity": portfolio.position_quantity(symbol),
            }
            decision = strategy.decide(state)
            if decision.action is not TradeAction.HOLD:
                pending_decisions[symbol] = decision

    return BacktestResult(
        strategy_name=strategy.name,
        metrics=_build_metrics(config.initial_cash, portfolio),
        trades=list(portfolio.trades),
        equity_curve=list(portfolio.snapshots),
    )


def _validate_features(features: pd.DataFrame) -> None:
    if features.empty:
        raise ValueError("Backtest features must not be empty.")
    missing = {"代码", "date", "open", "close", "volume", "return_1d"} - set(features.columns)
    if missing:
        raise ValueError(f"Backtest features missing required columns: {sorted(missing)}")


def _latest_prices(day_rows: pd.DataFrame) -> dict[str, float]:
    return {str(row["代码"]): float(row["close"]) for row in day_rows.to_dict("records")}


def _execution_prices(day_rows: pd.DataFrame, execution_price_column: str) -> dict[str, float]:
    return {
        str(row["代码"]): float(row[execution_price_column])
        for row in day_rows.to_dict("records")
    }


def _can_buy(row: dict[str, object], config: BacktestConfig) -> bool:
    if _is_suspended(row):
        return False
    return not _is_limit_up(row, config)


def _can_sell(row: dict[str, object], config: BacktestConfig) -> bool:
    if _is_suspended(row):
        return False
    return not _is_limit_down(row, config)


def _is_suspended(row: dict[str, object]) -> bool:
    volume = _float(row.get("volume"), 0.0)
    return volume <= 0


def _is_limit_up(row: dict[str, object], config: BacktestConfig) -> bool:
    return _execution_return(row, config) >= config.price_limit_rate - config.price_limit_tolerance


def _is_limit_down(row: dict[str, object], config: BacktestConfig) -> bool:
    return _execution_return(row, config) <= -config.price_limit_rate + config.price_limit_tolerance


def _execution_return(row: dict[str, object], config: BacktestConfig) -> float:
    previous_close = _float(row.get("previous_close"), 0.0)
    if previous_close > 0:
        execution_price = _float(row.get(config.execution_price_column), 0.0)
        return execution_price / previous_close - 1
    return _float(row.get("return_1d"), 0.0)


def _float(value: object, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if pd.isna(number):
        return default
    return number


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
        sharpe_ratio=round(_sharpe_ratio(portfolio), 10),
        max_drawdown=round(portfolio.max_drawdown, 10),
        trade_count=len(portfolio.trades),
        buy_count=buy_count,
        sell_count=sell_count,
        start_date=first.date,
        end_date=last.date,
    )


def _sharpe_ratio(portfolio: Portfolio) -> float:
    equities = [snapshot.equity for snapshot in portfolio.snapshots]
    if len(equities) < 2:
        return 0.0
    returns = pd.Series(equities).pct_change().dropna()
    if returns.empty:
        return 0.0
    volatility = returns.std()
    if volatility == 0 or pd.isna(volatility):
        return 0.0
    return float((returns.mean() / volatility) * (252**0.5))
