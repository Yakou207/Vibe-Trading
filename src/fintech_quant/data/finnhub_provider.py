from __future__ import annotations

from datetime import date
from typing import Any

from fintech_quant.data.base import MarketDataProvider


class FinnhubProvider(MarketDataProvider):
    name = "finnhub"

    def history(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        raise NotImplementedError("Finnhub data adapter will be implemented after API key setup.")
