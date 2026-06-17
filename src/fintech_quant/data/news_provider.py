from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class NewsRecord:
    symbol: str
    published_at: str
    title: str
    source: str
    url: str


def records_to_frame(records: list[NewsRecord]) -> pd.DataFrame:
    rows = [
        {
            "代码": record.symbol,
            "published_at": record.published_at,
            "title": record.title,
            "source": record.source,
            "url": record.url,
        }
        for record in records
    ]
    return pd.DataFrame(rows, columns=["代码", "published_at", "title", "source", "url"])
