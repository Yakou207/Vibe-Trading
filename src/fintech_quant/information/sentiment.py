from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from fintech_quant.information.models import InformationRecord


POSITIVE_KEYWORDS = (
    "增长",
    "盈利",
    "扭亏",
    "预增",
    "中标",
    "回购",
    "增持",
    "支持",
    "突破",
    "改善",
)
NEGATIVE_KEYWORDS = (
    "退市",
    "问询",
    "处罚",
    "亏损",
    "减值",
    "立案",
    "风险",
    "下滑",
    "违约",
    "冻结",
)


@dataclass(frozen=True)
class TextSentiment:
    score: float
    positive_keywords: tuple[str, ...]
    negative_keywords: tuple[str, ...]


def analyze_text_sentiment(text: str) -> TextSentiment:
    positive = tuple(keyword for keyword in POSITIVE_KEYWORDS if keyword in text)
    negative = tuple(keyword for keyword in NEGATIVE_KEYWORDS if keyword in text)
    score = 0.0 if not positive and not negative else (len(positive) - len(negative)) / (len(positive) + len(negative))
    return TextSentiment(round(score, 6), positive, negative)


def analyze_information_records(records: list[InformationRecord]) -> tuple[list[InformationRecord], int]:
    analyzed: list[InformationRecord] = []
    negative_count = 0
    for record in records:
        sentiment = analyze_text_sentiment(_record_text(record))
        metadata = {
            **record.metadata,
            "text_sentiment_score": sentiment.score,
            "positive_keywords": list(sentiment.positive_keywords),
            "negative_keywords": list(sentiment.negative_keywords),
        }
        risk_tags = list(record.risk_tags)
        if sentiment.score < 0 and "negative_text_sentiment" not in risk_tags:
            risk_tags.append("negative_text_sentiment")
            negative_count += 1
        analyzed.append(replace(record, risk_tags=tuple(risk_tags), metadata=metadata))
    return analyzed, negative_count


def _record_text(record: InformationRecord) -> str:
    parts = [record.title, record.summary]
    raw_text_path = record.metadata.get("raw_text_path")
    if isinstance(raw_text_path, str):
        path = Path(raw_text_path)
        if path.exists():
            parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return " ".join(part for part in parts if part)
