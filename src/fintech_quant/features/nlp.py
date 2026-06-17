from __future__ import annotations

import pandas as pd


def build_news_attention_features(news: pd.DataFrame) -> pd.DataFrame:
    frame = news.copy()
    frame["date"] = pd.to_datetime(frame["published_at"]).dt.date.astype(str)
    if "source" not in frame.columns:
        frame["source"] = ""
    return (
        frame.groupby(["代码", "date"], as_index=False)
        .agg(
            news_count=("title", "size"),
            unique_source_count=("source", "nunique"),
        )
        .sort_values(["代码", "date"])
        .reset_index(drop=True)
    )
