from __future__ import annotations

import pandas as pd


def build_daily_sentiment_features(news: pd.DataFrame) -> pd.DataFrame:
    frame = _with_daily_date(news)
    if "sentiment_score" not in frame.columns:
        frame["sentiment_score"] = 0.0
    grouped = frame.groupby(["代码", "date"], as_index=False)
    result = grouped.agg(
        sentiment_score_mean=("sentiment_score", "mean"),
        sentiment_score_min=("sentiment_score", "min"),
        sentiment_score_max=("sentiment_score", "max"),
        sentiment_item_count=("sentiment_score", "size"),
    )
    negative = (
        frame.assign(is_negative=frame["sentiment_score"] < 0)
        .groupby(["代码", "date"], as_index=False)
        .agg(negative_news_ratio=("is_negative", "mean"))
    )
    return result.merge(negative, on=["代码", "date"], how="left")


def _with_daily_date(news: pd.DataFrame) -> pd.DataFrame:
    frame = news.copy()
    frame["date"] = pd.to_datetime(frame["published_at"]).dt.date.astype(str)
    return frame
