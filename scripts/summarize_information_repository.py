from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.data import normalize_a_share_symbol  # noqa: E402
from fintech_quant.information import InformationRecord, InformationRepository  # noqa: E402
from fintech_quant.research.scoring import NEGATIVE_RISK_TAGS  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize the local information repository.")
    parser.add_argument("--input", default="data/raw/information/information.jsonl")
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--sector", default=None)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--recent-days", type=int, default=30)
    parser.add_argument("--output", default="outputs/information_repository_summary.json")
    args = parser.parse_args()

    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    records = _filter_records(
        InformationRepository(Path(args.input)).all_records(),
        symbol=args.symbol,
        sector=args.sector,
    )
    payload = _build_summary(records, as_of=as_of, recent_days=args.recent_days)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"summary_path={output_path}")
    print(f"record_count={payload['record_count']}")
    print(f"negative_record_count={payload['negative_record_count']}")
    return 0


def _filter_records(
    records: list[InformationRecord],
    *,
    symbol: str | None,
    sector: str | None,
) -> list[InformationRecord]:
    if symbol is None and sector is None:
        return records
    normalized_symbol = normalize_a_share_symbol(symbol) if symbol else None
    return [
        record
        for record in records
        if (normalized_symbol is not None and record.normalized_symbol == normalized_symbol)
        or (sector is not None and record.sector == sector)
    ]


def _build_summary(records: list[InformationRecord], *, as_of: date, recent_days: int) -> dict[str, object]:
    if recent_days <= 0:
        raise ValueError("--recent-days must be positive")
    ordered_records = sorted(records, key=lambda record: (record.published_at, record.normalized_symbol or "", record.title))
    negative_records = [record for record in ordered_records if any(tag in NEGATIVE_RISK_TAGS for tag in record.risk_tags)]
    recent_cutoff = as_of - timedelta(days=recent_days - 1)
    recent_negative_records = [
        record for record in negative_records if recent_cutoff <= record.published_at <= as_of
    ]
    return {
        "as_of": as_of.isoformat(),
        "recent_days": recent_days,
        "record_count": len(ordered_records),
        "negative_record_count": len(negative_records),
        "category_counts": dict(Counter(record.category.value for record in ordered_records)),
        "retention_counts": dict(Counter(record.retention_class.value for record in ordered_records)),
        "risk_tag_counts": dict(Counter(tag for record in ordered_records for tag in record.risk_tags)),
        "source_counts": dict(Counter(record.source for record in ordered_records)),
        "archive_summary": _archive_summary(ordered_records),
        "keyword_counts": _keyword_counts(ordered_records),
        "retention_class_summary": _retention_class_summary(
            ordered_records,
            recent_cutoff=recent_cutoff,
            as_of=as_of,
        ),
        "by_symbol": _grouped_entity_summary(
            ordered_records,
            key_fn=lambda record: record.normalized_symbol,
            recent_cutoff=recent_cutoff,
            as_of=as_of,
        ),
        "by_sector": _grouped_entity_summary(
            ordered_records,
            key_fn=lambda record: record.sector,
            recent_cutoff=recent_cutoff,
            as_of=as_of,
        ),
        "recent_negative_records": [_record_to_summary(record) for record in recent_negative_records[-20:]],
    }


def _retention_class_summary(
    records: list[InformationRecord],
    *,
    recent_cutoff: date,
    as_of: date,
) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[InformationRecord]] = {}
    for record in records:
        grouped.setdefault(record.retention_class.value, []).append(record)
    return {
        retention_class: _entity_summary(class_records, recent_cutoff=recent_cutoff, as_of=as_of)
        for retention_class, class_records in sorted(grouped.items())
    }


def _grouped_entity_summary(
    records: list[InformationRecord],
    *,
    key_fn: Callable[[InformationRecord], str | None],
    recent_cutoff: date,
    as_of: date,
) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[InformationRecord]] = {}
    for record in records:
        key = key_fn(record)
        if key:
            grouped.setdefault(key, []).append(record)
    return {
        key: _entity_summary(entity_records, recent_cutoff=recent_cutoff, as_of=as_of)
        for key, entity_records in sorted(grouped.items())
    }


def _entity_summary(
    records: list[InformationRecord],
    *,
    recent_cutoff: date,
    as_of: date,
) -> dict[str, object]:
    ordered_records = sorted(records, key=lambda record: (record.published_at, record.normalized_symbol or "", record.title))
    negative_records = [record for record in ordered_records if any(tag in NEGATIVE_RISK_TAGS for tag in record.risk_tags)]
    recent_negative_records = [
        record for record in negative_records if recent_cutoff <= record.published_at <= as_of
    ]
    return {
        "record_count": len(ordered_records),
        "negative_record_count": len(negative_records),
        "recent_negative_record_count": len(recent_negative_records),
        "category_counts": dict(Counter(record.category.value for record in ordered_records)),
        "retention_counts": dict(Counter(record.retention_class.value for record in ordered_records)),
        "risk_tag_counts": dict(Counter(tag for record in ordered_records for tag in record.risk_tags)),
        "source_counts": dict(Counter(record.source for record in ordered_records)),
        "symbols": sorted({record.normalized_symbol for record in ordered_records if record.normalized_symbol}),
        "sectors": sorted({record.sector for record in ordered_records if record.sector}),
        "oldest_published_at": ordered_records[0].published_at.isoformat() if ordered_records else None,
        "newest_published_at": ordered_records[-1].published_at.isoformat() if ordered_records else None,
        "latest_financial_report_at": _latest_category_date(ordered_records, "financial_report"),
        "latest_stock_data_at": _latest_category_date(ordered_records, "stock_data"),
        "latest_policy_at": _latest_category_date(ordered_records, "regulatory_policy"),
        "recent_negative_titles": [record.title for record in recent_negative_records[-10:]],
    }


def _latest_category_date(records: list[InformationRecord], category: str) -> str | None:
    dates = [record.published_at for record in records if record.category.value == category]
    return max(dates).isoformat() if dates else None


def _archive_summary(records: list[InformationRecord]) -> dict[str, int]:
    text_chars = [_int_metadata(record, "text_chars") for record in records]
    return {
        "archived_document_count": sum(1 for record in records if record.metadata.get("raw_document_path")),
        "extracted_text_count": sum(1 for record in records if record.metadata.get("raw_text_path")),
        "total_text_chars": sum(value for value in text_chars if value is not None),
    }


def _keyword_counts(records: list[InformationRecord]) -> dict[str, dict[str, int]]:
    positive = Counter[str]()
    negative = Counter[str]()
    for record in records:
        positive.update(str(keyword) for keyword in record.metadata.get("positive_keywords", ()) if keyword)
        negative.update(str(keyword) for keyword in record.metadata.get("negative_keywords", ()) if keyword)
    return {"positive": dict(positive), "negative": dict(negative)}


def _int_metadata(record: InformationRecord, key: str) -> int | None:
    value = record.metadata.get(key)
    if value in (None, ""):
        return None
    return int(value)


def _record_to_summary(record: InformationRecord) -> dict[str, object]:
    return {
        "symbol": record.normalized_symbol,
        "sector": record.sector,
        "published_at": record.published_at.isoformat(),
        "source": record.source,
        "category": record.category.value,
        "title": record.title,
        "risk_tags": list(record.risk_tags),
        "text_sentiment_score": record.metadata.get("text_sentiment_score"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
