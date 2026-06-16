from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any


class MarketDataProvider(ABC):
    name: str

    @abstractmethod
    def history(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        """Return daily bars or records for a symbol."""
