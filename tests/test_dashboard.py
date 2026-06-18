import unittest


class DashboardTest(unittest.TestCase):
    def test_dashboard_module_imports_without_streamlit_runtime(self) -> None:
        from fintech_quant.reports import dashboard

        self.assertTrue(callable(dashboard.main))
        self.assertEqual(dashboard.format_percent(0.1234), "12.34%")
        self.assertEqual(dashboard.format_percent(-0.05), "-5.00%")

    def test_select_latest_window_prefers_latest_test_end(self) -> None:
        from fintech_quant.reports.dashboard import select_latest_window

        rows = [
            {"validation_mode": "rolling", "window_name": "rolling_1", "test_end": "2024-01-01"},
            {"validation_mode": "rolling", "window_name": "rolling_2", "test_end": "2025-01-01"},
            {"validation_mode": "expanding", "window_name": "expanding_1", "test_end": "2024-01-01"},
        ]

        latest = select_latest_window(rows, validation_mode="rolling")

        self.assertEqual(latest, "rolling_2")


if __name__ == "__main__":
    unittest.main()
