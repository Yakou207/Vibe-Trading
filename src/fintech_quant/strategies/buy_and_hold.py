from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

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
