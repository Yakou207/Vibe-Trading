from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from fintech_quant.trading import TradeDecision


class Strategy(ABC):
    name: str

    @abstractmethod
    def decide(self, state: dict[str, Any]) -> TradeDecision:
        """Return a trading decision for one instrument state."""
