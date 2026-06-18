import unittest


class MetricsTest(unittest.TestCase):
    def test_equity_curve_metrics_include_return_sharpe_and_drawdown(self) -> None:
        from fintech_quant.backtesting.metrics import calculate_equity_metrics

        equity_curve = [
            {"date": "2024-01-01", "equity": 100.0},
            {"date": "2024-01-02", "equity": 110.0},
            {"date": "2024-01-03", "equity": 105.0},
            {"date": "2024-01-04", "equity": 120.0},
        ]

        metrics = calculate_equity_metrics(equity_curve, periods_per_year=252)

        self.assertEqual(metrics.start_date, "2024-01-01")
        self.assertEqual(metrics.end_date, "2024-01-04")
        self.assertAlmostEqual(metrics.total_return, 0.2)
        self.assertAlmostEqual(metrics.max_drawdown, -0.0454545455)
        self.assertGreater(metrics.sharpe_ratio, 0.0)

    def test_flat_equity_curve_has_zero_risk_metrics(self) -> None:
        from fintech_quant.backtesting.metrics import calculate_equity_metrics

        equity_curve = [
            {"date": "2024-01-01", "equity": 100.0},
            {"date": "2024-01-02", "equity": 100.0},
            {"date": "2024-01-03", "equity": 100.0},
        ]

        metrics = calculate_equity_metrics(equity_curve)

        self.assertEqual(metrics.total_return, 0.0)
        self.assertEqual(metrics.max_drawdown, 0.0)
        self.assertEqual(metrics.sharpe_ratio, 0.0)


if __name__ == "__main__":
    unittest.main()
