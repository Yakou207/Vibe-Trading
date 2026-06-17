from __future__ import annotations

import unittest

import pandas as pd


class RlVsBaselineReportTest(unittest.TestCase):
    def test_report_contains_rl_and_buy_hold_metrics_for_same_test_window(self) -> None:
        from fintech_quant.reports.rl_vs_baseline import run_q_learning_walk_forward_report
        from fintech_quant.training.q_learning import QLearningConfig

        rows = []
        for date in pd.date_range("2020-01-01", "2023-12-31", freq="90D"):
            close = 10.0 + len(rows)
            rows.append(
                {
                    "代码": "sh688001",
                    "date": date.date().isoformat(),
                    "open": close,
                    "close": close,
                    "volume": 1000,
                    "return_1d": 0.01,
                    "rsi_14": 80.0,
                    "macd_hist": 0.2,
                    "return_5d": 0.1,
                    "volatility_20": 0.01,
                    "target_next_return_1d": 0.05,
                }
            )
        features = pd.DataFrame(rows)

        report = run_q_learning_walk_forward_report(
            features,
            q_config=QLearningConfig(episodes=2, epsilon=0.0, seed=1),
            train_years=2,
            test_years=1,
            initial_cash=10_000.0,
            target_weight=0.5,
            max_position_weight=0.6,
            commission_rate=0.0,
            stamp_tax_rate=0.0,
            slippage_rate=0.0,
        )

        self.assertEqual(report["strategy"], "q_learning_v1")
        self.assertEqual(len(report["windows"]), 1)
        window = report["windows"][0]
        self.assertEqual(window["train_start"], "2020-01-01")
        self.assertEqual(window["test_start"], "2022-01-01")
        self.assertIn("rl_metrics", window)
        self.assertIn("buy_hold_metrics", window)
        self.assertEqual(window["rl_metrics"]["start_date"], window["buy_hold_metrics"]["start_date"])
        self.assertEqual(window["rl_metrics"]["end_date"], window["buy_hold_metrics"]["end_date"])
        self.assertIn("excess_total_return", window)
        self.assertGreater(window["q_state_count"], 0)


if __name__ == "__main__":
    unittest.main()
