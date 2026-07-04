from __future__ import annotations

import calendar
import json
from collections import Counter
from dataclasses import asdict
from datetime import date
from pathlib import Path

from fintech_quant.data.symbols import normalize_a_share_symbol
from fintech_quant.information.models import InformationCategory, InformationRecord, RetentionClass


class InformationRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: InformationRecord) -> bool:
        existing_ids = {item.record_id for item in self._read_all()}
        if record.record_id in existing_ids:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(self._to_json(record), ensure_ascii=False, sort_keys=True) + "\n")
        return True

    def all_records(self) -> list[InformationRecord]:
        return self._read_all()

    def replace_all(self, records: list[InformationRecord]) -> None:
        self._write_all(records)

    def export_by_retention_class(self, output_dir: Path) -> dict[str, object]:
        output_dir.mkdir(parents=True, exist_ok=True)
        records = sorted(
            self._read_all(),
            key=lambda record: (
                record.retention_class.value,
                record.published_at,
                record.normalized_symbol or "",
                record.title,
            ),
        )
        classes: dict[str, dict[str, object]] = {}
        for retention_class in RetentionClass:
            class_records = [record for record in records if record.retention_class is retention_class]
            output_path = output_dir / f"{retention_class.value}.jsonl"
            self._write_jsonl(output_path, class_records)
            classes[retention_class.value] = _class_manifest(output_path, class_records)
        manifest = {
            "source": str(self.path),
            "output_dir": str(output_dir),
            "record_count": len(records),
            "classes": classes,
        }
        (output_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return manifest

    def query(
        self,
        symbol: str | None = None,
        sector: str | None = None,
        category: InformationCategory | None = None,
    ) -> list[InformationRecord]:
        normalized_symbol = normalize_a_share_symbol(symbol) if symbol else None
        records = self._read_all()
        if normalized_symbol is not None:
            records = [record for record in records if record.normalized_symbol == normalized_symbol]
        if sector is not None:
            records = [record for record in records if record.sector == sector]
        if category is not None:
            records = [record for record in records if record.category is category]
        return sorted(records, key=lambda record: record.published_at)

    def prune_text_records(self, today: date) -> int:
        cutoff_day = min(today.day, calendar.monthrange(today.year - 3, today.month)[1])
        cutoff = date(today.year - 3, today.month, cutoff_day)
        records = self._read_all()
        kept = [
            record
            for record in records
            if record.retention_class is RetentionClass.SELECTED_UNIVERSE_STOCK_DATA
            or record.published_at >= cutoff
        ]
        removed = len(records) - len(kept)
        self._write_all(kept)
        return removed

    def _read_all(self) -> list[InformationRecord]:
        if not self.path.exists():
            return []
        records: list[InformationRecord] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    records.append(self._from_json(json.loads(line)))
        return records

    def _write_all(self, records: list[InformationRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_jsonl(self.path, records)

    def _write_jsonl(self, path: Path, records: list[InformationRecord]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(self._to_json(record), ensure_ascii=False, sort_keys=True) + "\n")

    def _to_json(self, record: InformationRecord) -> dict[str, object]:
        data = asdict(record)
        data["symbol"] = record.normalized_symbol
        data["published_at"] = record.published_at.isoformat()
        data["category"] = record.category.value
        data["retention_class"] = record.retention_class.value
        data["record_id"] = record.record_id
        return data

    def _from_json(self, data: dict[str, object]) -> InformationRecord:
        return InformationRecord(
            symbol=data.get("symbol") if isinstance(data.get("symbol"), str) else None,
            sector=data.get("sector") if isinstance(data.get("sector"), str) else None,
            published_at=date.fromisoformat(str(data["published_at"])),
            source=str(data["source"]),
            category=InformationCategory(str(data["category"])),
            title=str(data["title"]),
            url=str(data.get("url", "")),
            summary=str(data.get("summary", "")),
            risk_tags=tuple(data.get("risk_tags", ())),
            metadata=dict(data.get("metadata", {})),
        )


def _class_manifest(path: Path, records: list[InformationRecord]) -> dict[str, object]:
    dates = [record.published_at for record in records]
    symbols = sorted({record.normalized_symbol for record in records if record.normalized_symbol})
    return {
        "path": str(path),
        "record_count": len(records),
        "category_counts": dict(Counter(record.category.value for record in records)),
        "source_counts": dict(Counter(record.source for record in records)),
        "symbols": symbols,
        "oldest_published_at": min(dates).isoformat() if dates else None,
        "newest_published_at": max(dates).isoformat() if dates else None,
    }
