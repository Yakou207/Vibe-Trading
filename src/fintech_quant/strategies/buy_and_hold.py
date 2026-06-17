from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from fintech_quant.strategies.base import Strategy
from fintech_quant.trading import TradeAction, TradeDecision
from fintech_quant.training.walk_forward import WalkForwardWindow, slice_window


@dataclass(frozen=True)
class BuyAndHoldResult:
    window_name: str
    train_start: object
    train_end: object
    test_start: object
    test_end: object
    train_rows: int
    test_rows: int
    test_cumulative_return: float


def evaluate_buy_and_hold(features: pd.DataFrame, window: WalkForwardWindow) -> BuyAndHoldResult:
    train, test = slice_window(features, window)
    test_returns = (
        test.dropna(subset=["target_next_return_1d"])
        .groupby("date")["target_next_return_1d"]
        .mean()
        .sort_index()
    )
    cumulative_return = float((1 + test_returns).prod() - 1) if len(test_returns) else 0.0
    return BuyAndHoldResult(
        window_name=window.name,
        train_start=window.train_start,
        train_end=window.train_end,
        test_start=window.test_start,
        test_end=window.test_end,
        train_rows=len(train),
        test_rows=len(test),
        test_cumulative_return=round(cumulative_return, 10),
    )


@dataclass(frozen=True)
class EqualWeightBuyAndHoldStrategy(Strategy):
    name: str = "equal_weight_buy_and_hold"
    target_weight: float = 0.1

    def decide(self, state: dict[str, Any]) -> TradeDecision:
        if int(state.get("position_quantity", 0)) > 0:
            return TradeDecision(TradeAction.HOLD, 1.0, "Already holding this symbol.")
        return TradeDecision(TradeAction.BUY, self.target_weight, "Buy once, then hold.")
