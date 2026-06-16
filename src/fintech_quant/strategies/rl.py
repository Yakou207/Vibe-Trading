from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fintech_quant.strategies.base import Strategy
from fintech_quant.trading import TradeAction, TradeDecision


@dataclass(frozen=True)
class RlBuySellHoldStrategy(Strategy):
    name: str = "rl_bsh_v0"

    def decide(self, state: dict[str, Any]) -> TradeDecision:
        return TradeDecision(
            action=TradeAction.HOLD,
            confidence=0.0,
            reason="Untrained RL policy defaults to hold.",
        )
