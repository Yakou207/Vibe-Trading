from __future__ import annotations

import unittest

import pandas as pd


class StrategyComparisonReportTest(unittest.TestCase):
    def test_comparison_report_contains_metrics_and_rl_diagnostics(self) -> None:
        from fintech_quant.reports.strategy_comparison import run_strategy_comparison_report
        from fintech_quant.training.dqn import DQNConfig
        from fintech_quant.training.q_learning import QLearningConfig

        rows = []
        for date in pd.date_range("2020-01-01", "2024-12-31", freq="90D"):
            index = len(rows)
            rows.append(
                {
                    "代码": "sh688001",
                    "date": date.date().isoformat(),
                    "open": 10.0 + index,
                    "close": 10.0 + index,
                    "volume": 1000,
                    "return_1d": 0.01,
                    "rsi_14": 45.0 if index % 2 == 0 else 75.0,
                    "macd_hist": 0.2 if index % 2 == 0 else -0.2,
                    "return_5d": 0.1,
                    "volatility_20": 0.01,
                    "target_next_return_1d": 0.05,
                }
            )
        report = run_strategy_comparison_report(
            pd.DataFrame(rows),
            q_config=QLearningConfig(episodes=2, epsilon=0.0, seed=1),
            dqn_config=DQNConfig(episodes=1, epsilon=0.0, batch_size=2, seed=1),
            train_years=2,
            test_years=1,
            initial_cash=10_000.0,
            target_weight=0.5,
            max_position_weight=0.6,
            commission_rate=0.0,
            stamp_tax_rate=0.0,
            slippage_rate=0.0,
        )

        self.assertEqual(report["report"], "strategy_comparison_diagnostics")
        self.assertIn("validation_modes", report)
        self.assertEqual(set(report["validation_modes"]), {"rolling", "expanding"})
        self.assertEqual(len(report["windows"]), len(report["validation_modes"]["rolling"]))
        self.assertGreaterEqual(len(report["validation_modes"]["rolling"]), 1)
        self.assertGreaterEqual(len(report["validation_modes"]["expanding"]), 1)
        self.assertIn("look_ahead_bias_controls", report["validation"])
        window = report["windows"][0]
        self.assertEqual(window["validation_mode"], "rolling")
        self.assertLess(window["train_end"], window["test_start"])
        self.assertEqual(
            set(window["strategies"]),
            {
                "hold_only",
                "equal_weight_buy_and_hold",
                "rsi_macd_rule",
                "q_learning_v1",
                "dqn_v1",
            },
        )
        for metrics in window["strategies"].values():
            self.assertIn("sharpe_ratio", metrics)
            self.assertIn("total_return", metrics)
        self.assertIn("q_learning_v1_vs_equal_weight_buy_and_hold", window["excess_returns"])
        self.assertIn("dqn_v1_vs_equal_weight_buy_and_hold", window["excess_returns"])
        diagnostics = window["rl_diagnostics"]
        self.assertGreater(diagnostics["q_state_count"], 0)
        self.assertIn("buy", diagnostics["action_counts"])
        self.assertIn("sell", diagnostics["action_counts"])
        self.assertIn("decision_action_counts", diagnostics)
        self.assertIn("hold", diagnostics["decision_action_counts"])
        self.assertIn("top_buy_states", diagnostics)
        self.assertIn("top_sell_states", diagnostics)
        dqn_diagnostics = window["dqn_diagnostics"]
        self.assertIn("feature_columns", dqn_diagnostics)
        self.assertNotIn("target_next_return_1d", dqn_diagnostics["feature_columns"])
        self.assertNotIn("target_action", dqn_diagnostics["feature_columns"])
        self.assertEqual(dqn_diagnostics["scaler_fit_start"], window["train_start"])
        self.assertEqual(dqn_diagnostics["scaler_fit_end"], window["train_end"])
        self.assertEqual(dqn_diagnostics["scaler_fit_rows"], window["train_rows"])
        self.assertIn("decision_action_counts", dqn_diagnostics)
        self.assertIn("hold", dqn_diagnostics["decision_action_counts"])

        expanding_window = report["validation_modes"]["expanding"][0]
        self.assertEqual(expanding_window["validation_mode"], "expanding")
        self.assertLess(expanding_window["train_end"], expanding_window["test_start"])
        self.assertEqual(
            expanding_window["dqn_diagnostics"]["scaler_fit_end"],
            expanding_window["train_end"],
        )


if __name__ == "__main__":
    unittest.main()
