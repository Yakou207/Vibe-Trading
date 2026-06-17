from __future__ import annotations

import unittest


class RuleBaselineTest(unittest.TestCase):
    def test_rsi_macd_rule_buys_positive_momentum_when_flat(self) -> None:
        from fintech_quant.strategies.rule_based import RsiMacdRuleStrategy
        from fintech_quant.trading import TradeAction

        decision = RsiMacdRuleStrategy(target_weight=0.2).decide(
            {
                "rsi_14": 45.0,
                "macd_hist": 0.1,
                "position_quantity": 0,
            }
        )

        self.assertEqual(decision.action, TradeAction.BUY)
        self.assertEqual(decision.confidence, 0.2)

    def test_rsi_macd_rule_sells_overbought_or_negative_momentum_when_long(self) -> None:
        from fintech_quant.strategies.rule_based import RsiMacdRuleStrategy
        from fintech_quant.trading import TradeAction

        decision = RsiMacdRuleStrategy().decide(
            {
                "rsi_14": 75.0,
                "macd_hist": 0.1,
                "position_quantity": 100,
            }
        )

        self.assertEqual(decision.action, TradeAction.SELL)

    def test_rsi_macd_rule_holds_without_signal(self) -> None:
        from fintech_quant.strategies.rule_based import RsiMacdRuleStrategy
        from fintech_quant.trading import TradeAction

        decision = RsiMacdRuleStrategy().decide(
            {
                "rsi_14": 55.0,
                "macd_hist": -0.1,
                "position_quantity": 0,
            }
        )

        self.assertEqual(decision.action, TradeAction.HOLD)


if __name__ == "__main__":
    unittest.main()
