from __future__ import annotations

from datetime import date
from typing import Any

from fintech_quant.data.base import MarketDataProvider


class AkShareProvider(MarketDataProvider):
    name = "akshare"

    def history(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        raise NotImplementedError("AkShare data adapter will be implemented after data schema approval.")
