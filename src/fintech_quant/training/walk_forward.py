from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class WalkForwardWindow:
    name: str
    train_start: date
    train_end: date
    test_start: date
    test_end: date


def rolling_windows(
    dates: pd.Series | pd.DatetimeIndex,
    train_years: int = 2,
    test_years: int = 1,
) -> list[WalkForwardWindow]:
    ordered = _ordered_dates(dates)
    windows: list[WalkForwardWindow] = []
    start = ordered.min()
    max_date = ordered.max()
    index = 1
    while True:
        train_start = start
        train_end = train_start + pd.DateOffset(years=train_years) - pd.DateOffset(days=1)
        test_start = train_end + pd.DateOffset(days=1)
        test_end = test_start + pd.DateOffset(years=test_years) - pd.DateOffset(days=1)
        if test_end > max_date:
            break
        windows.append(
            WalkForwardWindow(
                name=f"rolling_{index}",
                train_start=train_start.date(),
                train_end=train_end.date(),
                test_start=test_start.date(),
                test_end=test_end.date(),
            )
        )
        start = start + pd.DateOffset(years=test_years)
        index += 1
    return windows


def expanding_windows(
    dates: pd.Series | pd.DatetimeIndex,
    initial_train_years: int = 2,
    test_years: int = 1,
) -> list[WalkForwardWindow]:
    ordered = _ordered_dates(dates)
    train_start = ordered.min()
    max_date = ordered.max()
    windows: list[WalkForwardWindow] = []
    train_end = train_start + pd.DateOffset(years=initial_train_years) - pd.DateOffset(days=1)
    index = 1
    while True:
        test_start = train_end + pd.DateOffset(days=1)
        test_end = test_start + pd.DateOffset(years=test_years) - pd.DateOffset(days=1)
        if test_end > max_date:
            break
        windows.append(
            WalkForwardWindow(
                name=f"expanding_{index}",
                train_start=train_start.date(),
                train_end=train_end.date(),
                test_start=test_start.date(),
                test_end=test_end.date(),
            )
        )
        train_end = train_end + pd.DateOffset(years=test_years)
        index += 1
    return windows


def slice_window(frame: pd.DataFrame, window: WalkForwardWindow) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.to_datetime(frame["date"]).dt.date
    train = frame[(dates >= window.train_start) & (dates <= window.train_end)].copy()
    test = frame[(dates >= window.test_start) & (dates <= window.test_end)].copy()
    return train, test


def _ordered_dates(dates: pd.Series | pd.DatetimeIndex) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(dates).dropna().sort_values().unique())
