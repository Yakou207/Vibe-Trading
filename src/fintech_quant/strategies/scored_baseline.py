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
    min_confidence: float = 0.8

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
        if score.confidence < self.min_confidence:
            return TradeDecision(
                action=TradeAction.HOLD,
                confidence=score.confidence,
                reason=f"Score confidence {score.confidence} is below minimum {self.min_confidence}.",
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


@dataclass(frozen=True)
class ScoredRlOverlayStrategy(Strategy):
    base_strategy: ScoredBaselineStrategy
    name: str = "scored_rl_overlay_v0"
    buy_weight_multiplier: float = 1.0
    hold_weight_multiplier: float = 0.5

    def decide(self, state: dict[str, Any]) -> TradeDecision:
        base_decision = self.base_strategy.decide(state)
        if base_decision.action is TradeAction.SELL:
            return base_decision

        rl_action = _rl_action(state.get("rl_action"))
        if rl_action is None:
            return base_decision

        position_quantity = int(state.get("position_quantity", 0) or 0)
        if base_decision.action is TradeAction.BUY:
            if rl_action == "sell":
                return TradeDecision(
                    action=TradeAction.HOLD,
                    confidence=0.0,
                    reason=f"RL overlay vetoes scored buy. Base reason: {base_decision.reason}",
                )
            multiplier = self.buy_weight_multiplier if rl_action == "buy" else self.hold_weight_multiplier
            return TradeDecision(
                action=TradeAction.BUY,
                confidence=_clamp_confidence(base_decision.confidence * multiplier),
                reason=f"RL overlay {rl_action} scales scored buy. Base reason: {base_decision.reason}",
            )

        if base_decision.action is TradeAction.HOLD and rl_action == "sell" and position_quantity > 0:
            return TradeDecision(
                action=TradeAction.SELL,
                confidence=1.0,
                reason=f"RL overlay exit signal while scored baseline is holding. Base reason: {base_decision.reason}",
            )
        return base_decision


def _rl_action(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"buy", "hold", "sell"}:
        return text
    raise ValueError(f"Unsupported rl_action: {value!r}")


def _clamp_confidence(value: float) -> float:
    return min(1.0, max(0.0, round(float(value), 6)))
