from __future__ import annotations

from datetime import date
from typing import Any

from fintech_quant.data.base import MarketDataProvider


class YahooProvider(MarketDataProvider):
    name = "yahoo"

    def history(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        raise NotImplementedError("Yahoo Finance adapter will be implemented after data schema approval.")
