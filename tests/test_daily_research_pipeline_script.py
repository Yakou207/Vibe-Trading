from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class DailyResearchPipelineScriptTest(unittest.TestCase):
    def test_daily_pipeline_help_exposes_tushare_fundamental_information_source(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.pop("TUSHARE_TOKEN", None)

        result = subprocess.run(
            [sys.executable, "scripts/run_daily_research_pipeline.py", "--help"],
            cwd=worktree,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("tushare_fundamental", result.stdout)
        self.assertIn("preflight-data-sources", result.stdout)

    def test_daily_pipeline_builds_information_features_market_state_and_rl_dataset(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.pop("TUSHARE_TOKEN", None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            bars_path = root / "bars.json"
            information_input = root / "seed_information.jsonl"
            market_input = root / "index.csv"
            information_output = root / "information.jsonl"
            classified_information_output_dir = root / "classified_information"
            daily_output = root / "daily.csv"
            feature_output = root / "features.csv"
            market_output = root / "market_state.csv"
            rl_output = root / "rl_state.jsonl"
            rl_policy_report_output = root / "rl_policy_report.json"
            dqn_policy_report_output = root / "dqn_policy_report.json"
            strategy_comparison_output = root / "strategy_comparison.json"
            scoring_coverage_output = root / "scoring_coverage.json"
            data_source_health_output = root / "data_source_health.json"
            report_output_root = root / "reports"

            universe_path.write_text("symbol,name,sector\n000001,平安银行,银行\n", encoding="utf-8")
            bars_path.write_text(
                json.dumps(
                    [
                        _bar("000001", "2026-01-01", 10.0),
                        _bar("000001", "2026-01-02", 10.5, limit_up=True),
                    ],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            information_input.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "symbol": "000001",
                                "sector": None,
                                "published_at": "2026-01-02",
                                "source": "fixture",
                                "category": "company_announcement",
                                "title": "监管问询",
                                "url": "",
                                "summary": "公司收到监管问询。",
                                "risk_tags": [],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        json.dumps(
                            {
                                "symbol": None,
                                "sector": "银行",
                                "published_at": "2026-01-02",
                                "source": "fixture",
                                "category": "regulatory_policy",
                                "title": "银行板块监管政策",
                                "url": "",
                                "summary": "银行板块资本监管政策更新。",
                                "risk_tags": ["regulatory_policy"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            market_input.write_text("date,close\n2026-01-01,100\n2026-01-02,99\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_daily_research_pipeline.py",
                    "--universe",
                    str(universe_path),
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-01-02",
                    "--price-source",
                    "json",
                    "--price-input",
                    str(bars_path),
                    "--information-source",
                    "jsonl",
                    "--information-input",
                    str(information_input),
                    "--market-source",
                    "csv",
                    "--market-input",
                    str(market_input),
                    "--information-output",
                    str(information_output),
                    "--classified-information-output-dir",
                    str(classified_information_output_dir),
                    "--daily-output",
                    str(daily_output),
                    "--feature-output",
                    str(feature_output),
                    "--market-output",
                    str(market_output),
                    "--rl-output",
                    str(rl_output),
                    "--rl-policy-report-output",
                    str(rl_policy_report_output),
                    "--rl-policy",
                    "buy_and_hold",
                    "--rl-policy-symbol",
                    "000001.SZ",
                    "--rl-policy-transaction-cost",
                    "0.001",
                    "--dqn-policy-report-output",
                    str(dqn_policy_report_output),
                    "--dqn-policy-symbol",
                    "000001.SZ",
                    "--dqn-epochs",
                    "20",
                    "--dqn-policy-transaction-cost",
                    "0.001",
                    "--strategy-comparison-output",
                    str(strategy_comparison_output),
                    "--scoring-coverage-output",
                    str(scoring_coverage_output),
                    "--buy-threshold",
                    "65",
                    "--min-score-confidence",
                    "0.75",
                    "--max-main-outflow-days",
                    "2",
                    "--broad-market-drop-threshold",
                    "10",
                    "--preflight-data-sources",
                    "--preflight-data-source-checks",
                    "tushare_daily",
                    "--data-source-health-output",
                    str(data_source_health_output),
                    "--run-id",
                    "fixture-pipeline",
                    "--report-output-root",
                    str(report_output_root),
                    "--ma-window",
                    "2",
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("pipeline_steps=13", result.stdout)
            self.assertIn(f"classified_information_output_dir={classified_information_output_dir}", result.stdout)
            self.assertIn(f"dqn_policy_report_output={dqn_policy_report_output}", result.stdout)
            self.assertIn(f"strategy_comparison_output={strategy_comparison_output}", result.stdout)
            self.assertTrue(daily_output.exists())
            self.assertTrue(feature_output.exists())
            self.assertTrue(market_output.exists())
            self.assertTrue(rl_output.exists())
            self.assertTrue(rl_policy_report_output.exists())
            self.assertTrue(dqn_policy_report_output.exists())
            self.assertTrue(strategy_comparison_output.exists())
            self.assertTrue(scoring_coverage_output.exists())
            self.assertTrue(data_source_health_output.exists())
            self.assertTrue((classified_information_output_dir / "manifest.json").exists())
            self.assertTrue((classified_information_output_dir / "text_financial_report.jsonl").exists())
            self.assertTrue((classified_information_output_dir / "selected_universe_stock_data.jsonl").exists())
            self.assertTrue((report_output_root / "fixture-pipeline" / "run_report.json").exists())
            information_records = [
                json.loads(line)
                for line in information_output.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            rl_record = json.loads(rl_output.read_text(encoding="utf-8").splitlines()[0])
            rl_policy_report = json.loads(rl_policy_report_output.read_text(encoding="utf-8"))
            dqn_policy_report = json.loads(dqn_policy_report_output.read_text(encoding="utf-8"))
            strategy_comparison = json.loads(strategy_comparison_output.read_text(encoding="utf-8"))
            scoring_coverage = json.loads(scoring_coverage_output.read_text(encoding="utf-8"))
            data_source_health = json.loads(data_source_health_output.read_text(encoding="utf-8"))
            classified_manifest = json.loads(
                (classified_information_output_dir / "manifest.json").read_text(encoding="utf-8")
            )
            run_report = json.loads(
                (report_output_root / "fixture-pipeline" / "run_report.json").read_text(encoding="utf-8")
            )

        titles = {record["title"] for record in information_records}
        company_record = next(record for record in information_records if record["title"] == "监管问询")
        self.assertIn("监管问询", titles)
        self.assertIn("银行板块监管政策", titles)
        self.assertIn("negative_text_sentiment", company_record["risk_tags"])
        self.assertIn("state_vector", rl_record)
        self.assertIn("state_fields", rl_record)
        self.assertEqual(rl_record["symbol"], "000001.SZ")
        self.assertEqual(rl_policy_report["strategy_config"]["policy"], "buy_and_hold")
        self.assertEqual(rl_policy_report["strategy_config"]["symbol"], "000001.SZ")
        self.assertEqual(rl_policy_report["summary"]["ending_equity"], 1.049)
        self.assertEqual(dqn_policy_report["strategy_config"]["policy"], "linear_q_dqn_v0")
        self.assertEqual(dqn_policy_report["strategy_config"]["symbol"], "000001.SZ")
        self.assertEqual(dqn_policy_report["summary"]["ending_equity"], 1.049)
        self.assertEqual(strategy_comparison["baseline"]["name"], "fixture-pipeline")
        self.assertEqual(strategy_comparison["candidate"]["name"], "fixture-pipeline-linear-q-dqn")
        self.assertIn("excess_return", strategy_comparison)
        self.assertEqual(scoring_coverage["pipeline"], "a_share_daily_factor_pipeline_v0")
        self.assertEqual(scoring_coverage["row_count"], 2)
        self.assertEqual(data_source_health["symbols"], ["000001.SZ"])
        self.assertEqual(data_source_health["summary"], {"ok": 0, "failed": 0, "skipped": 1})
        self.assertEqual(data_source_health["checks"][0]["name"], "tushare_daily")
        self.assertEqual(classified_manifest["classes"]["text_financial_report"]["record_count"], 2)
        self.assertEqual(run_report["strategy_config"]["buy_threshold"], 65.0)
        self.assertEqual(run_report["strategy_config"]["min_confidence"], 0.75)
        self.assertEqual(run_report["risk_limits"]["max_main_outflow_days"], 2)
        self.assertEqual(run_report["risk_limits"]["broad_market_drop_threshold"], 10)

    def test_daily_pipeline_requires_dqn_report_when_strategy_comparison_is_requested(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)

        result = subprocess.run(
            [
                sys.executable,
                "scripts/run_daily_research_pipeline.py",
                "--universe",
                "universe.csv",
                "--start",
                "2026-01-01",
                "--end",
                "2026-01-02",
                "--price-source",
                "json",
                "--price-input",
                "bars.json",
                "--information-source",
                "jsonl",
                "--information-input",
                "information.jsonl",
                "--market-source",
                "csv",
                "--market-input",
                "index.csv",
                "--strategy-comparison-output",
                "comparison.json",
            ],
            cwd=worktree,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--dqn-policy-report-output is required", result.stderr)


def _bar(symbol: str, trade_date: str, close: float, *, limit_up: bool | None = None) -> dict[str, object]:
    row: dict[str, object] = {
        "symbol": symbol,
        "trade_date": trade_date,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1000.0,
        "amount": close * 1000.0,
        "source": "fixture",
    }
    if limit_up is not None:
        row["limit_up"] = limit_up
    return row


if __name__ == "__main__":
    unittest.main()
