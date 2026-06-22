from __future__ import annotations

import importlib
import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from fintech_quant.data.errors import MissingProviderDependency, ProviderFetchError
from fintech_quant.data.symbols import normalize_a_share_symbol
from fintech_quant.information.models import InformationCategory, InformationRecord


class InformationFetcher(ABC):
    @abstractmethod
    def fetch(
        self,
        symbol: str | None,
        sector: str | None,
        start: date,
        end: date,
    ) -> list[InformationRecord]:
        """Return source-backed information records for the requested scope."""


class StaticInformationFetcher(InformationFetcher):
    def __init__(self, records: list[InformationRecord]) -> None:
        self._records = records

    def fetch(
        self,
        symbol: str | None,
        sector: str | None,
        start: date,
        end: date,
    ) -> list[InformationRecord]:
        return _filter_records(self._records, symbol, sector, start, end)


class JsonlInformationFetcher(InformationFetcher):
    def __init__(self, path: Path) -> None:
        self._path = path

    def fetch(
        self,
        symbol: str | None,
        sector: str | None,
        start: date,
        end: date,
    ) -> list[InformationRecord]:
        if not self._path.exists():
            return []

        records: list[InformationRecord] = []
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    records.append(_record_from_json(json.loads(line)))
        return _filter_records(records, symbol, sector, start, end)


class AkShareNoticeFetcher(InformationFetcher):
    def __init__(
        self,
        report_type: str = "重大事项",
        recent_page: int = 1,
        fetcher: Callable[[], object] | None = None,
    ) -> None:
        self._report_type = report_type
        self._recent_page = recent_page
        self._fetcher = fetcher

    def fetch(
        self,
        symbol: str | None,
        sector: str | None,
        start: date,
        end: date,
    ) -> list[InformationRecord]:
        rows = self._fetch_rows()
        records = [_record_from_notice_row(row, self._report_type) for row in rows]
        return _filter_records(records, symbol, sector, start, end)

    def _fetch_rows(self) -> list[dict[str, object]]:
        if self._fetcher is not None:
            return self._run_fetch(self._fetcher)

        try:
            ak = importlib.import_module("akshare")
        except ImportError as exc:
            raise MissingProviderDependency("akshare is required for AkShareNoticeFetcher") from exc

        return self._run_fetch(
            lambda: ak.stock_notice_report(
                report_type=self._report_type,
                recent_page=self._recent_page,
            ).to_dict(orient="records")
        )

    def _run_fetch(self, fetcher: Callable[[], object]) -> list[dict[str, object]]:
        try:
            return list(fetcher())
        except Exception as exc:
            raise ProviderFetchError(
                f"akshare notice fetch failed for report_type={self._report_type!r}, recent_page={self._recent_page!r}"
            ) from exc


def _filter_records(
    records: list[InformationRecord],
    symbol: str | None,
    sector: str | None,
    start: date,
    end: date,
) -> list[InformationRecord]:
    normalized_symbol = normalize_a_share_symbol(symbol) if symbol else None
    return [
        record
        for record in records
        if start <= record.published_at <= end
        and (normalized_symbol is None or record.normalized_symbol == normalized_symbol)
        and (sector is None or record.sector == sector)
    ]


def _record_from_json(data: dict[str, object]) -> InformationRecord:
    return InformationRecord(
        symbol=data.get("symbol") if isinstance(data.get("symbol"), str) else None,
        sector=data.get("sector") if isinstance(data.get("sector"), str) else None,
        published_at=_parse_date(data["published_at"]),
        source=str(data["source"]),
        category=InformationCategory(str(data["category"])),
        title=str(data["title"]),
        url=str(data.get("url", "")),
        summary=str(data.get("summary", "")),
        risk_tags=tuple(str(tag) for tag in data.get("risk_tags", ())),
    )


def _record_from_notice_row(row: dict[str, object], report_type: str) -> InformationRecord:
    category = InformationCategory.FINANCIAL_REPORT if report_type == "财务报告" else InformationCategory.COMPANY_ANNOUNCEMENT
    risk_tags = ("negative_announcement",) if report_type == "风险提示" else ()
    return InformationRecord(
        symbol=str(row["代码"]).strip().zfill(6),
        sector=None,
        published_at=_parse_date(row["公告日期"]),
        source="akshare_notice",
        category=category,
        title=str(row["公告标题"]).strip(),
        url="",
        summary=str(row.get("公告类型", "")).strip(),
        risk_tags=risk_tags,
    )


def _parse_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw_value = str(value).strip()
    if len(raw_value) == 8 and raw_value.isdigit():
        return datetime.strptime(raw_value, "%Y%m%d").date()
    return datetime.fromisoformat(raw_value).date()
