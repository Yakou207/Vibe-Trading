from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class FundamentalRecord:
    symbol: str
    date: str
    pe: float | None = None
    pb: float | None = None
    roe: float | None = None
    revenue_growth: float | None = None
    profit_growth: float | None = None
    debt_ratio: float | None = None


def records_to_frame(records: list[FundamentalRecord]) -> pd.DataFrame:
    rows = [
        {
            "代码": record.symbol,
            "date": record.date,
            "pe": record.pe,
            "pb": record.pb,
            "roe": record.roe,
            "revenue_growth": record.revenue_growth,
            "profit_growth": record.profit_growth,
            "debt_ratio": record.debt_ratio,
        }
        for record in records
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "代码",
            "date",
            "pe",
            "pb",
            "roe",
            "revenue_growth",
            "profit_growth",
            "debt_ratio",
        ],
    )
