from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ResearchDashboardTest(unittest.TestCase):
    def test_script_writes_research_dashboard_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            strategy_json = tmp / "strategy.json"
            factor_json = tmp / "factor.json"
            data_quality_json = tmp / "quality.json"
            output_html = tmp / "dashboard.html"
            strategy_json.write_text(
                json.dumps(
                    {
                        "report": "strategy_comparison_diagnostics",
                        "validation": {
                            "look_ahead_bias_controls": [
                                "DQN scaler is fit only on each in-sample train window.",
                                "Out-of-sample rows are used only for backtesting.",
                            ]
                        },
                        "dqn": {"episodes": 1, "epsilon": 0.2},
                        "validation_modes": {
                            "rolling": [
                                {
                                    "window_name": "rolling_1",
                                    "strategies": {},
                                    "dqn_diagnostics": {},
                                }
                            ],
                            "expanding": [
                                {
                                    "window_name": "expanding_1",
                                    "strategies": {},
                                    "dqn_diagnostics": {},
                                }
                            ],
                        },
                        "windows": [
                            {
                                "window_name": "rolling_1",
                                "strategies": {
                                    "equal_weight_buy_and_hold": {
                                        "total_return": 0.1,
                                        "sharpe_ratio": 1.0,
                                        "max_drawdown": -0.1,
                                        "trade_count": 1,
                                    },
                                    "q_learning_v1": {
                                        "total_return": 0.05,
                                        "sharpe_ratio": 0.5,
                                        "max_drawdown": -0.05,
                                        "trade_count": 2,
                                    },
                                    "dqn_v1": {
                                        "total_return": 0.08,
                                        "sharpe_ratio": 0.8,
                                        "max_drawdown": -0.04,
                                        "trade_count": 3,
                                    },
                                },
                                "dqn_diagnostics": {
                                    "feature_columns": ["rsi_14"],
                                    "decision_action_counts": {"buy": 1, "hold": 2, "sell": 0},
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            factor_json.write_text(
                json.dumps(
                    {
                        "report": "factor_diagnostics",
                        "factor_count": 1,
                        "top_abs_ic": [
                            {
                                "factor": "rsi_14",
                                "ic": 0.4,
                                "rank_ic": 0.5,
                                "coverage": 1.0,
                                "group": "oscillator",
                            }
                        ],
                        "factors": {
                            "rsi_14": {
                                "ic": 0.4,
                                "rank_ic": 0.5,
                                "coverage": 1.0,
                                "group": "oscillator",
                                "direction": "positive",
                            }
                        },
                        "warnings": [],
                    }
                ),
                encoding="utf-8",
            )
            data_quality_json.write_text(
                json.dumps({"symbols": 30, "rows": 29334, "date_min": "2021-06-16", "date_max": "2026-06-16"}),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_research_dashboard.py",
                    "--strategy-report",
                    str(strategy_json),
                    "--factor-report",
                    str(factor_json),
                    "--data-quality-report",
                    str(data_quality_json),
                    "--output",
                    str(output_html),
                ],
                check=False,
                cwd=Path(__file__).resolve().parents[1],
                env={"PYTHONPATH": "src"},
                text=True,
                capture_output=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            html = output_html.read_text(encoding="utf-8")
            self.assertIn("Strategy Comparison", html)
            self.assertIn("Validation Modes", html)
            self.assertIn("rolling", html)
            self.assertIn("expanding", html)
            self.assertIn("DQN", html)
            self.assertIn("Factor Diagnostics", html)
            self.assertIn("rsi_14", html)


if __name__ == "__main__":
    unittest.main()
