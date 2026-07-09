from __future__ import annotations

import unittest


class ScoredBaselineStrategyTest(unittest.TestCase):
    def test_buys_when_score_is_high_and_risk_allows(self) -> None:
        from fintech_quant.features import ScoreInput, score_stock
        from fintech_quant.risk import RiskAction
        from fintech_quant.strategies.scored_baseline import ScoredBaselineStrategy
        from fintech_quant.trading import TradeAction

        strategy = ScoredBaselineStrategy(buy_threshold=70.0)
        decision = strategy.decide(
            {
                "score": score_stock(
                    ScoreInput(
                        symbol="000001",
                        pe=18,
                        pb=1.5,
                        roe=0.16,
                        growth=0.12,
                        close_above_ma20=True,
                        close_above_ma60=True,
                        rsi=55,
                        macd_positive=True,
                        volume_confirmed=True,
                        main_net_inflow=1,
                        main_outflow_days=0,
                        margin_financing_positive=True,
                        limit_up_streak=1,
                        dragon_tiger_positive=True,
                        negative_event_count=0,
                    )
                ),
                "risk_action": RiskAction.NONE,
            }
        )

        self.assertEqual(decision.action, TradeAction.BUY)
        self.assertGreater(decision.confidence, 0.0)

    def test_risk_reduce_overrides_high_score(self) -> None:
        from fintech_quant.features import ScoreInput, score_stock
        from fintech_quant.risk import RiskAction
        from fintech_quant.strategies.scored_baseline import ScoredBaselineStrategy
        from fintech_quant.trading import TradeAction

        strategy = ScoredBaselineStrategy(buy_threshold=70.0)
        score = score_stock(
            ScoreInput(
                symbol="000001",
                pe=18,
                pb=1.5,
                roe=0.16,
                growth=0.12,
                close_above_ma20=True,
                close_above_ma60=True,
                rsi=55,
                macd_positive=True,
                volume_confirmed=True,
                main_net_inflow=1,
                main_outflow_days=0,
                margin_financing_positive=True,
                limit_up_streak=1,
                dragon_tiger_positive=True,
                negative_event_count=0,
            )
        )

        decision = strategy.decide({"score": score, "risk_action": RiskAction.REDUCE})

        self.assertEqual(decision.action, TradeAction.SELL)
        self.assertIn("risk", decision.reason.lower())

    def test_holds_high_score_when_confidence_is_below_minimum(self) -> None:
        from fintech_quant.features import ComponentScore, StockScore
        from fintech_quant.risk import RiskAction
        from fintech_quant.strategies.scored_baseline import ScoredBaselineStrategy
        from fintech_quant.trading import TradeAction

        strategy = ScoredBaselineStrategy(buy_threshold=70.0, min_confidence=0.8)
        score = StockScore(
            symbol="000001.SZ",
            total=90.0,
            components={
                "fundamental": ComponentScore("fundamental", 35.0, 35.0, ()),
                "technical": ComponentScore("technical", 25.0, 25.0, ()),
                "capital_flow": ComponentScore("capital_flow", 25.0, 25.0, ()),
                "sentiment": ComponentScore("sentiment", 5.0, 15.0, ()),
            },
            confidence=0.6,
            missing_fields=("dragon_tiger_positive", "negative_event_count"),
        )

        decision = strategy.decide({"score": score, "risk_action": RiskAction.NONE})

        self.assertEqual(decision.action, TradeAction.HOLD)
        self.assertEqual(decision.confidence, 0.6)
        self.assertIn("confidence", decision.reason.lower())

    def test_holds_when_score_is_below_threshold(self) -> None:
        from fintech_quant.features import ScoreInput, score_stock
        from fintech_quant.risk import RiskAction
        from fintech_quant.strategies.scored_baseline import ScoredBaselineStrategy
        from fintech_quant.trading import TradeAction

        strategy = ScoredBaselineStrategy(buy_threshold=70.0)
        decision = strategy.decide(
            {
                "score": score_stock(ScoreInput(symbol="000001")),
                "risk_action": RiskAction.NONE,
            }
        )

        self.assertEqual(decision.action, TradeAction.HOLD)

    def test_rl_overlay_scales_scored_buy_position_without_selecting_stock(self) -> None:
        from fintech_quant.risk import RiskAction
        from fintech_quant.strategies.scored_baseline import ScoredBaselineStrategy, ScoredRlOverlayStrategy
        from fintech_quant.trading import TradeAction

        strategy = ScoredRlOverlayStrategy(
            base_strategy=ScoredBaselineStrategy(buy_threshold=70.0),
            buy_weight_multiplier=0.5,
        )

        decision = strategy.decide(
            {
                "score": _stock_score(total=85.0, confidence=1.0),
                "risk_action": RiskAction.NONE,
                "rl_action": "buy",
            }
        )

        self.assertEqual(decision.action, TradeAction.BUY)
        self.assertEqual(decision.confidence, 0.5)
        self.assertIn("RL overlay", decision.reason)

    def test_rl_overlay_can_veto_new_scored_buy_without_creating_short_signal(self) -> None:
        from fintech_quant.risk import RiskAction
        from fintech_quant.strategies.scored_baseline import ScoredBaselineStrategy, ScoredRlOverlayStrategy
        from fintech_quant.trading import TradeAction

        strategy = ScoredRlOverlayStrategy(base_strategy=ScoredBaselineStrategy(buy_threshold=70.0))

        decision = strategy.decide(
            {
                "score": _stock_score(total=85.0, confidence=1.0),
                "risk_action": RiskAction.NONE,
                "rl_action": "sell",
                "position_quantity": 0,
            }
        )

        self.assertEqual(decision.action, TradeAction.HOLD)
        self.assertEqual(decision.confidence, 0.0)
        self.assertIn("veto", decision.reason.lower())

    def test_rl_overlay_can_exit_existing_position_when_score_no_longer_buys(self) -> None:
        from fintech_quant.risk import RiskAction
        from fintech_quant.strategies.scored_baseline import ScoredBaselineStrategy, ScoredRlOverlayStrategy
        from fintech_quant.trading import TradeAction

        strategy = ScoredRlOverlayStrategy(base_strategy=ScoredBaselineStrategy(buy_threshold=70.0))

        decision = strategy.decide(
            {
                "score": _stock_score(total=60.0, confidence=1.0),
                "risk_action": RiskAction.NONE,
                "rl_action": "sell",
                "position_quantity": 100,
            }
        )

        self.assertEqual(decision.action, TradeAction.SELL)
        self.assertEqual(decision.confidence, 1.0)
        self.assertIn("exit", decision.reason.lower())

def _stock_score(total: float, confidence: float) -> "StockScore":
    from fintech_quant.features import ComponentScore, StockScore

    return StockScore(
        symbol="000001.SZ",
        total=total,
        components={
            "fundamental": ComponentScore("fundamental", 35.0, 35.0, ()),
            "technical": ComponentScore("technical", 25.0, 25.0, ()),
            "capital_flow": ComponentScore("capital_flow", 25.0, 25.0, ()),
            "sentiment": ComponentScore("sentiment", 15.0, 15.0, ()),
        },
        confidence=confidence,
        missing_fields=(),
    )


if __name__ == "__main__":
    unittest.main()
