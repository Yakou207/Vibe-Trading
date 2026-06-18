from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from fintech_quant.data.symbols import normalize_a_share_symbol
from fintech_quant.information.models import InformationRecord


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
        normalized_symbol = normalize_a_share_symbol(symbol) if symbol else None
        return [
            record
            for record in self._records
            if start <= record.published_at <= end
            and (normalized_symbol is None or record.normalized_symbol == normalized_symbol)
            and (sector is None or record.sector == sector)
        ]
