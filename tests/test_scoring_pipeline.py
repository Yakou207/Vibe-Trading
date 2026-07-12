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

    def test_price_volume_proxy_is_scored_without_claiming_main_capital_flow(self) -> None:
        from fintech_quant.features import ScoreInput, score_stock

        result = score_stock(
            ScoreInput(
                symbol="000001",
                flow_proxy_kind="price_volume_cmf_obv",
                price_volume_flow_signal=0.2,
                price_volume_outflow_days=2,
            )
        )

        capital = result.components["capital_flow"]
        self.assertEqual(capital.score, 17.5)
        self.assertIn("Price-volume proxy is positive; it is not actual main-capital flow.", capital.reasons)
        self.assertNotIn("Main capital is net inflow.", capital.reasons)
        self.assertNotIn("main_net_inflow", result.missing_fields)

    def test_real_main_flow_takes_precedence_over_proxy_fields(self) -> None:
        from fintech_quant.features import ScoreInput, score_stock

        result = score_stock(
            ScoreInput(
                symbol="000001",
                main_net_inflow=-1.0,
                main_outflow_days=5,
                flow_proxy_kind="price_volume_cmf_obv",
                price_volume_flow_signal=0.2,
                price_volume_outflow_days=0,
            )
        )

        self.assertEqual(result.components["capital_flow"].score, 0.0)
        self.assertNotIn(
            "Price-volume proxy is positive; it is not actual main-capital flow.",
            result.components["capital_flow"].reasons,
        )


if __name__ == "__main__":
    unittest.main()
