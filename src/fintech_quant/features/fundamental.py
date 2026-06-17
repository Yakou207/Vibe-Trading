from __future__ import annotations

import pandas as pd


FUNDAMENTAL_FACTOR_COLUMNS = [
    "pe",
    "pb",
    "roe",
    "revenue_growth",
    "profit_growth",
    "debt_ratio",
]


def build_fundamental_feature_frame(fundamentals: pd.DataFrame) -> pd.DataFrame:
    frame = fundamentals.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date.astype(str)
    return frame.sort_values(["代码", "date"]).reset_index(drop=True)
