from __future__ import annotations

import unittest


class ScoringPipelineTest(unittest.TestCase):
    def test_scores_components_using_required_weights(self) -> None:
        from fintech_quant.features import ScoreInput, score_stock

        result = score_stock(
            ScoreInput(
                symbol="000001",
                pe=18.0,
                pb=1.5,
                roe=0.16,
                growth=0.12,
                close_above_ma20=True,
                close_above_ma60=True,
                relative_strength=0.8,
                rsi=55.0,
                macd_positive=True,
                volume_confirmed=True,
                main_net_inflow=1.0,
                main_outflow_days=0,
                margin_financing_positive=True,
                limit_up_streak=1,
                dragon_tiger_positive=True,
                negative_event_count=0,
            )
        )

        self.assertEqual(result.symbol, "000001.SZ")
        self.assertEqual(result.total, 100.0)
        self.assertEqual(result.components["fundamental"].max_score, 35.0)
        self.assertEqual(result.components["technical"].max_score, 25.0)
        self.assertEqual(result.components["capital_flow"].max_score, 25.0)
        self.assertEqual(result.components["sentiment"].max_score, 15.0)

    def test_technical_score_uses_relative_strength_rank(self) -> None:
        from fintech_quant.features import ScoreInput, score_stock

        result = score_stock(
            ScoreInput(
                symbol="000001",
                close_above_ma20=True,
                close_above_ma60=True,
                relative_strength=0.8,
                rsi=55.0,
                macd_positive=True,
                volume_confirmed=True,
            )
        )

        self.assertEqual(result.components["technical"].score, 25.0)
        self.assertIn("Relative strength ranks in the top 40% of the universe.", result.components["technical"].reasons)

    def test_missing_fields_reduce_confidence_without_fabricating_score(self) -> None:
        from fintech_quant.features import ScoreInput, score_stock

        result = score_stock(ScoreInput(symbol="000001"))

        self.assertLess(result.total, 100.0)
        self.assertLess(result.confidence, 1.0)
        self.assertIn("pe", result.missing_fields)
        self.assertIn("rsi", result.missing_fields)
        self.assertIn("relative_strength", result.missing_fields)


if __name__ == "__main__":
    unittest.main()
