from __future__ import annotations

import unittest


class RiskEngineTest(unittest.TestCase):
    def test_risk_limits_reject_invalid_thresholds(self) -> None:
        from fintech_quant.risk import RiskLimits

        invalid_cases = [
            ("max_position_weight", 0),
            ("max_portfolio_drawdown", -0.1),
            ("max_single_position_drawdown", 1.5),
            ("max_goodwill_ratio", -0.1),
            ("max_pledge_ratio", 1.1),
            ("max_main_outflow_days", -1),
            ("broad_market_drop_threshold", -1),
        ]

        for field, value in invalid_cases:
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, field):
                    RiskLimits(**{field: value})

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
                negative_event_count=1,
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
                "negative_event_count",
            },
        )

    def test_market_and_systemic_risks_emit_expected_actions(self) -> None:
        from fintech_quant.risk import RiskAction, RiskInput, evaluate_risk

        result = evaluate_risk(
            RiskInput(
                index_below_annual_ma=True,
                broad_market_drop_gt_3pct_count=16,
            )
        )

        self.assertEqual(result.action, RiskAction.REDUCE)
        self.assertEqual(
            {warning.rule for warning in result.warnings},
            {"index_below_annual_ma", "broad_market_drop_gt_3pct_count"},
        )

    def test_risk_rule_catalog_covers_layers_triggers_and_runtime_warnings(self) -> None:
        from fintech_quant.risk import RISK_RULE_CATALOG, RiskInput, evaluate_risk

        self.assertEqual(
            {item.layer for item in RISK_RULE_CATALOG},
            {
                "portfolio_drawdown",
                "single_stock_negative",
                "broad_market_abnormal",
                "systemic_risk",
            },
        )
        self.assertEqual(
            {item.rule for item in RISK_RULE_CATALOG},
            {
                "position_weight",
                "portfolio_drawdown",
                "single_position_drawdown",
                "st_warning",
                "negative_event_count",
                "goodwill_ratio",
                "pledge_ratio",
                "main_outflow_days",
                "index_below_annual_ma",
                "broad_market_drop_gt_3pct_count",
            },
        )

        result = evaluate_risk(
            RiskInput(
                position_weight=0.081,
                portfolio_drawdown=0.15,
                single_position_drawdown=0.081,
                st_warning=True,
                negative_event_count=1,
                goodwill_ratio=0.31,
                pledge_ratio=0.51,
                main_outflow_days=4,
                index_below_annual_ma=True,
                broad_market_drop_gt_3pct_count=16,
            )
        )
        catalog_rules = {item.rule for item in RISK_RULE_CATALOG}

        self.assertTrue({warning.rule for warning in result.warnings}.issubset(catalog_rules))


if __name__ == "__main__":
    unittest.main()
