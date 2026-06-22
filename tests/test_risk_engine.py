from __future__ import annotations

import unittest


class RiskEngineTest(unittest.TestCase):
    def test_portfolio_drawdown_15_percent_forces_liquidation(self) -> None:
        from fintech_quant.risk import RiskAction, RiskInput, evaluate_risk

        result = evaluate_risk(RiskInput(portfolio_drawdown=0.15))

        self.assertEqual(result.action, RiskAction.LIQUIDATE)
        self.assertIn("portfolio_drawdown", {warning.rule for warning in result.warnings})

    def test_single_stock_and_event_risks_emit_reduce_or_watch(self) -> None:
        from fintech_quant.risk import RiskAction, RiskInput, evaluate_risk

        result = evaluate_risk(
            RiskInput(
                position_weight=0.081,
                single_position_drawdown=0.081,
                st_warning=True,
                goodwill_ratio=0.31,
                pledge_ratio=0.51,
                main_outflow_days=4,
            )
        )

        self.assertEqual(result.action, RiskAction.REDUCE)
        self.assertEqual(
            {warning.rule for warning in result.warnings},
            {
                "position_weight",
                "single_position_drawdown",
                "st_warning",
                "goodwill_ratio",
                "pledge_ratio",
                "main_outflow_days",
            },
        )

    def test_market_and_systemic_risks_emit_expected_actions(self) -> None:
        from fintech_quant.risk import RiskAction, RiskInput, evaluate_risk

        result = evaluate_risk(
            RiskInput(
                index_below_annual_ma=True,
                broad_market_drop_count=16,
            )
        )

        self.assertEqual(result.action, RiskAction.REDUCE)
        self.assertEqual(
            {warning.rule for warning in result.warnings},
            {"index_below_annual_ma", "broad_market_drop_count"},
        )


if __name__ == "__main__":
    unittest.main()
