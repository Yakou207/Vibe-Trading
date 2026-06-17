from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from fintech_quant.backtesting.costs import CostModel
from fintech_quant.backtesting.portfolio import Order, Portfolio
from fintech_quant.features.indicators import feature_columns as default_feature_columns
from fintech_quant.risk.rules import RiskGate, RiskLimits


ACTION_NAMES = ("hold", "buy", "sell")


@dataclass
class AShareBuySellHoldEnvironment:
    features: pd.DataFrame
    feature_columns: list[str] | None = None
    initial_cash: float = 1_000_000.0
    target_weight: float = 0.1
    lot_size: int = 100
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.001
    slippage_rate: float = 0.0005
    max_position_weight: float = 1.0
    max_portfolio_drawdown: float = 0.2

    def __post_init__(self) -> None:
        if self.features.empty:
            raise ValueError("RL environment features must not be empty.")
        missing = {"代码", "date", "close"} - set(self.features.columns)
        if missing:
            raise ValueError(f"RL environment features missing required columns: {sorted(missing)}")
        self.frame = self.features.copy()
        self.frame["date"] = pd.to_datetime(self.frame["date"]).dt.date.astype(str)
        self.frame = self.frame.sort_values(["代码", "date"]).reset_index(drop=True)
        self.symbol = str(self.frame.iloc[0]["代码"])
        self.frame = self.frame[self.frame["代码"].astype(str) == self.symbol].reset_index(drop=True)
        columns = self.feature_columns or [
            column for column in default_feature_columns() if column in self.frame.columns
        ]
        self.feature_columns = columns or ["close"]
        self.portfolio = self._new_portfolio()
        self.risk_gate = self._new_risk_gate()
        self.index = 0
        self.action_names = ACTION_NAMES
        self.action_space = self._action_space()
        self.observation_space = self._observation_space()

    def reset(self, *, seed: int | None = None, options: dict[str, object] | None = None):
        self.portfolio = self._new_portfolio()
        self.risk_gate = self._new_risk_gate()
        self.index = 0
        return self._observation(), self._info("reset")

    def step(self, action: int):
        if self.index >= len(self.frame) - 1:
            return self._observation(), 0.0, True, False, self._info(_action_name(action))

        current = self.frame.iloc[self.index]
        current_price = float(current["close"])
        current_date = str(current["date"])
        previous_equity = self.portfolio.equity({self.symbol: current_price})
        action_name = _action_name(action)

        if action_name == "buy":
            target_value = previous_equity * self.target_weight
            quantity = int(target_value // current_price)
            order = Order(self.symbol, current_date, quantity, current_price)
            if self.risk_gate.evaluate_buy(
                self.portfolio,
                order,
                self.lot_size,
                {self.symbol: current_price},
            ).allowed:
                self.portfolio.buy(order, lot_size=self.lot_size)
        elif action_name == "sell":
            order = Order(
                self.symbol,
                current_date,
                self.portfolio.sellable_quantity(self.symbol),
                current_price,
            )
            if self.risk_gate.evaluate_sell(self.portfolio, order, self.lot_size).allowed:
                self.portfolio.sell(order, lot_size=self.lot_size)

        self.portfolio.close_trading_day(current_date)
        self.index += 1
        next_row = self.frame.iloc[self.index]
        next_price = float(next_row["close"])
        next_equity = self.portfolio.equity({self.symbol: next_price})
        reward = next_equity - previous_equity
        self.portfolio.record_snapshot(str(next_row["date"]), {self.symbol: next_price})
        terminated = self.index >= len(self.frame) - 1
        return self._observation(), float(reward), terminated, False, self._info(action_name)

    def _new_portfolio(self) -> Portfolio:
        return Portfolio(
            initial_cash=self.initial_cash,
            cost_model=CostModel(
                commission_rate=self.commission_rate,
                stamp_tax_rate=self.stamp_tax_rate,
                slippage_rate=self.slippage_rate,
            ),
        )

    def _new_risk_gate(self) -> RiskGate:
        return RiskGate(
            RiskLimits(
                max_position_weight=self.max_position_weight,
                max_portfolio_drawdown=self.max_portfolio_drawdown,
            )
        )

    def _observation(self) -> list[float]:
        row = self.frame.iloc[self.index]
        return [float(row[column]) if pd.notna(row[column]) else 0.0 for column in self.feature_columns]

    def _info(self, action: str) -> dict[str, object]:
        row = self.frame.iloc[self.index]
        return {
            "symbol": self.symbol,
            "date": str(row["date"]),
            "action": action,
            "cash": self.portfolio.cash,
            "position_quantity": self.portfolio.position_quantity(self.symbol),
        }

    def _action_space(self) -> object:
        try:
            from gymnasium import spaces

            return spaces.Discrete(len(ACTION_NAMES))
        except ImportError:
            return ACTION_NAMES

    def _observation_space(self) -> object:
        try:
            from gymnasium import spaces

            return spaces.Box(
                low=float("-inf"),
                high=float("inf"),
                shape=(len(self.feature_columns),),
                dtype=float,
            )
        except ImportError:
            return None


def _action_name(action: int) -> str:
    if action < 0 or action >= len(ACTION_NAMES):
        raise ValueError(f"Unknown action index: {action}")
    return ACTION_NAMES[action]
