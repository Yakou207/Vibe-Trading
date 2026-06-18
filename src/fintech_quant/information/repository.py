from __future__ import annotations

import json
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
        cutoff = date(today.year - 3, today.month, today.day)
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
        with self.path.open("w", encoding="utf-8") as handle:
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
        )
