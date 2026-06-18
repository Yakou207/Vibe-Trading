import unittest
from pathlib import Path


class DashboardTest(unittest.TestCase):
    def test_dashboard_module_imports_without_streamlit_runtime(self) -> None:
        from fintech_quant.reports import dashboard

        self.assertTrue(callable(dashboard.main))
        self.assertEqual(dashboard.format_percent(0.1234), "12.34%")
        self.assertEqual(dashboard.format_percent(-0.05), "-5.00%")

    def test_select_latest_window_prefers_latest_test_end(self) -> None:
        from fintech_quant.reports.dashboard import select_latest_window

        rows = [
            {
                "validation_mode": "rolling",
                "window_name": "rolling_1",
                "test_end": "2024-01-01",
            },
            {
                "validation_mode": "rolling",
                "window_name": "rolling_2",
                "test_end": "2025-01-01",
            },
            {
                "validation_mode": "expanding",
                "window_name": "expanding_1",
                "test_end": "2024-01-01",
            },
        ]

        latest = select_latest_window(rows, validation_mode="rolling")

        self.assertEqual(latest, "rolling_2")

    def test_strategy_recommendation_prefers_risk_adjusted_leader(self) -> None:
        from fintech_quant.reports.dashboard import strategy_recommendation

        rows = [
            {
                "strategy": "fast_model",
                "sharpe_ratio": 1.1,
                "total_return": 0.4,
                "max_drawdown": -0.35,
            },
            {
                "strategy": "robust_model",
                "sharpe_ratio": 1.8,
                "total_return": 0.25,
                "max_drawdown": -0.08,
            },
        ]

        recommendation = strategy_recommendation(rows)

        self.assertEqual(recommendation["strategy"], "robust_model")
        self.assertEqual(recommendation["risk_status"], "Researchable")
        self.assertIn("risk-adjusted", recommendation["reason"])

    def test_dashboard_uses_current_streamlit_width_api(self) -> None:
        source = Path("src/fintech_quant/reports/dashboard.py").read_text()

        self.assertNotIn("use_container_width", source)
        self.assertIn('width="stretch"', source)


if __name__ == "__main__":
    unittest.main()
