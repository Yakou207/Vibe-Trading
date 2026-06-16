from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TradeAction(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass(frozen=True)
class TradeDecision:
    action: TradeAction
    confidence: float
    reason: str
