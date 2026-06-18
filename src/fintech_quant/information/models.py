from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from enum import Enum

from fintech_quant.data.symbols import normalize_a_share_symbol


class InformationCategory(Enum):
    REGULATORY_POLICY = "regulatory_policy"
    FINANCIAL_REPORT = "financial_report"
    COMPANY_ANNOUNCEMENT = "company_announcement"
    SECTOR_EVENT = "sector_event"
    MARKET_SENTIMENT = "market_sentiment"
    STOCK_DATA = "stock_data"


class RetentionClass(Enum):
    TEXT_FINANCIAL_REPORT = "text_financial_report"
    SELECTED_UNIVERSE_STOCK_DATA = "selected_universe_stock_data"


TEXT_CATEGORIES = {
    InformationCategory.REGULATORY_POLICY,
    InformationCategory.FINANCIAL_REPORT,
    InformationCategory.COMPANY_ANNOUNCEMENT,
    InformationCategory.SECTOR_EVENT,
    InformationCategory.MARKET_SENTIMENT,
}


@dataclass(frozen=True)
class InformationRecord:
    symbol: str | None
    sector: str | None
    published_at: date
    source: str
    category: InformationCategory
    title: str
    url: str
    summary: str
    risk_tags: tuple[str, ...] = ()

    @property
    def normalized_symbol(self) -> str | None:
        return normalize_a_share_symbol(self.symbol) if self.symbol else None

    @property
    def retention_class(self) -> RetentionClass:
        if self.category is InformationCategory.STOCK_DATA:
            return RetentionClass.SELECTED_UNIVERSE_STOCK_DATA
        return RetentionClass.TEXT_FINANCIAL_REPORT

    @property
    def record_id(self) -> str:
        payload = "|".join(
            [
                self.source,
                self.url,
                self.title,
                self.normalized_symbol or "",
                self.sector or "",
                self.published_at.isoformat(),
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
