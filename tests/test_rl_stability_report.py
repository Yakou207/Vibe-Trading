from __future__ import annotations

import unittest

import pandas as pd


class RlStabilityReportTest(unittest.TestCase):
    def test_stability_report_groups_runs_by_episode_count(self) -> None:
        from fintech_quant.reports.rl_stability import run_rl_stability_report

        rows = []
        for date in pd.date_range("2020-01-01", "2023-12-31", freq="90D"):
            index = len(rows)
            rows.append(
                {
                    "代码": "sh688001",
                    "date": date.date().isoformat(),
                    "open": 10.0 + index,
                    "close": 10.0 + index,
                    "volume": 1000,
                    "return_1d": 0.01,
                    "rsi_14": 45.0,
                    "macd_hist": 0.2,
                    "return_20d": 0.1,
                    "close_to_ma_20": 0.1,
                    "ma_20_slope": 0.1,
                    "volatility_20": 0.01,
                    "target_next_return_1d": 0.05,
                }
            )

        report = run_rl_stability_report(
            features=pd.DataFrame(rows),
            seeds=[1, 2],
            episode_counts=[2, 3],
            train_years=2,
            test_years=1,
            initial_cash=10_000.0,
            target_weight=0.5,
            max_position_weight=0.6,
            commission_rate=0.0,
            stamp_tax_rate=0.0,
            slippage_rate=0.0,
        )

        self.assertEqual(report["report"], "rl_stability")
        self.assertEqual(set(report["summary_by_episodes"]), {"2", "3"})
        self.assertEqual(len(report["runs"]), 4)
        for summary in report["summary_by_episodes"].values():
            self.assertIn("mean_total_return", summary)
            self.assertIn("std_total_return", summary)
            self.assertIn("win_rate_vs_buy_hold", summary)
            self.assertIn("mean_trade_count", summary)
        self.assertIn("warnings", report)


if __name__ == "__main__":
    unittest.main()
