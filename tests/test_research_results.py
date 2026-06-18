import json
import tempfile
import unittest
from pathlib import Path


class ResearchResultsTest(unittest.TestCase):
    def test_dashboard_config_supports_non_daily_future_sources(self) -> None:
        from fintech_quant.reports.research_results import DashboardConfig

        config = DashboardConfig(
            market="a_share",
            frequency="1m",
            execution_mode="paper",
            strategy_comparison_path=Path("custom/strategy.json"),
            equity_curve_path=Path("custom/equity.json"),
        )

        self.assertEqual(config.frequency, "1m")
        self.assertEqual(config.execution_mode, "paper")
        self.assertEqual(config.strategy_comparison_path, Path("custom/strategy.json"))

    def test_load_strategy_comparison_flattens_validation_windows(self) -> None:
        from fintech_quant.reports.research_results import load_strategy_comparison

        payload = {
            "validation_modes": {
                "rolling": [
                    {
                        "window_name": "rolling_1",
                        "validation_mode": "rolling",
                        "train_start": "2021-01-01",
                        "train_end": "2022-01-01",
                        "test_start": "2022-01-02",
                        "test_end": "2022-12-31",
                        "train_rows": 100,
                        "test_rows": 50,
                        "strategies": {
                            "rsi_macd_rule": {
                                "total_return": 0.12,
                                "annualized_return": 0.11,
                                "sharpe_ratio": 1.2,
                                "max_drawdown": -0.08,
                                "trade_count": 30,
                                "final_equity": 1120000.0,
                            }
                        },
                    }
                ]
            }
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "strategy_comparison_report.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            rows = load_strategy_comparison(path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["validation_mode"], "rolling")
        self.assertEqual(rows[0]["window_name"], "rolling_1")
        self.assertEqual(rows[0]["strategy"], "rsi_macd_rule")
        self.assertEqual(rows[0]["sharpe_ratio"], 1.2)
        self.assertEqual(rows[0]["max_drawdown"], -0.08)

    def test_build_dashboard_model_uses_real_result_contract(self) -> None:
        from fintech_quant.reports.research_results import DashboardDataSource

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs = root / "outputs"
            outputs.mkdir()
            processed = root / "data" / "processed"
            processed.mkdir(parents=True)

            (outputs / "strategy_comparison_report.json").write_text(
                json.dumps(
                    {
                        "validation_modes": {
                            "rolling": [
                                {
                                    "window_name": "rolling_1",
                                    "validation_mode": "rolling",
                                    "train_start": "2021-01-01",
                                    "train_end": "2022-01-01",
                                    "test_start": "2022-01-02",
                                    "test_end": "2022-12-31",
                                    "train_rows": 100,
                                    "test_rows": 50,
                                    "strategies": {
                                        "buy_hold": {
                                            "total_return": 0.10,
                                            "annualized_return": 0.09,
                                            "sharpe_ratio": 1.0,
                                            "max_drawdown": -0.05,
                                            "trade_count": 2,
                                            "final_equity": 1100000.0,
                                        }
                                    },
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            (outputs / "baseline_backtest.json").write_text(
                json.dumps(
                    {
                        "strategy": "buy_hold",
                        "metrics": {"total_return": 0.10},
                        "equity_curve": [
                            {"date": "2022-01-02", "equity": 100.0, "drawdown": 0.0},
                            {"date": "2022-01-03", "equity": 110.0, "drawdown": 0.0},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (outputs / "data_quality_report.json").write_text(
                json.dumps({"rows": 150, "symbols": 3, "passes_core_checks": True}),
                encoding="utf-8",
            )
            (processed / "akshare_research_features.csv").write_text(
                "date,代码,close,target_action\n2022-01-02,sh688001,10,buy\n",
                encoding="utf-8",
            )

            model = DashboardDataSource(root).load()

        self.assertEqual(model["source_status"]["strategy_comparison"], "ready")
        self.assertEqual(model["config"]["frequency"], "1d")
        self.assertEqual(model["config"]["execution_mode"], "research")
        self.assertEqual(len(model["strategy_rows"]), 1)
        self.assertEqual(len(model["equity_curve"]), 2)
        self.assertEqual(model["data_quality"]["passes_core_checks"], True)


if __name__ == "__main__":
    unittest.main()
