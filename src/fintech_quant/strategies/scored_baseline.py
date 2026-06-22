from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fintech_quant.features import StockScore
from fintech_quant.risk import RiskAction
from fintech_quant.strategies.base import Strategy
from fintech_quant.trading import TradeAction, TradeDecision


@dataclass(frozen=True)
class ScoredBaselineStrategy(Strategy):
    name: str = "scored_baseline_v0"
    buy_threshold: float = 70.0

    def decide(self, state: dict[str, Any]) -> TradeDecision:
        score = state["score"]
        risk_action = state.get("risk_action", RiskAction.NONE)
        if not isinstance(score, StockScore):
            raise TypeError("state['score'] must be a StockScore")
        if not isinstance(risk_action, RiskAction):
            raise TypeError("state['risk_action'] must be a RiskAction")

        if risk_action in {RiskAction.REDUCE, RiskAction.LIQUIDATE}:
            return TradeDecision(
                action=TradeAction.SELL,
                confidence=1.0,
                reason=f"Risk action {risk_action.value} overrides score {score.total}.",
            )
        if score.total >= self.buy_threshold:
            return TradeDecision(
                action=TradeAction.BUY,
                confidence=score.confidence,
                reason=f"Score {score.total} is above buy threshold {self.buy_threshold}.",
            )
        return TradeDecision(
            action=TradeAction.HOLD,
            confidence=score.confidence,
            reason=f"Score {score.total} is below buy threshold {self.buy_threshold}.",
        )
