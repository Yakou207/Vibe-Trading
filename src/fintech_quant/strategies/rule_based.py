from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fintech_quant.strategies.base import Strategy
from fintech_quant.trading import TradeAction, TradeDecision


@dataclass(frozen=True)
class RsiMacdRuleStrategy(Strategy):
    name: str = "rsi_macd_rule"
    target_weight: float = 0.1
    buy_rsi_max: float = 65.0
    sell_rsi_min: float = 70.0

    def decide(self, state: dict[str, Any]) -> TradeDecision:
        rsi = _float(state.get("rsi_14"), 50.0)
        macd_hist = _float(state.get("macd_hist"), 0.0)
        has_position = int(state.get("position_quantity", 0)) > 0
        if has_position and (rsi >= self.sell_rsi_min or macd_hist < 0):
            return TradeDecision(TradeAction.SELL, 1.0, "RSI/MACD exit signal.")
        if not has_position and rsi <= self.buy_rsi_max and macd_hist > 0:
            return TradeDecision(TradeAction.BUY, self.target_weight, "RSI/MACD entry signal.")
        return TradeDecision(TradeAction.HOLD, 0.0, "No RSI/MACD signal.")


def _float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
