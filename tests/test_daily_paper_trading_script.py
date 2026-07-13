from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class DailyPaperTradingScriptTest(unittest.TestCase):
    def test_daily_paper_trading_applies_close_risk_to_actual_position_before_queuing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            research_report = root / "run_report.json"
            features = root / "features.csv"
            account = root / "account.json"
            targets = root / "targets.csv"
            paper_report = root / "paper_report.json"
            research_report.write_text(
                json.dumps(
                    {
                        "scores": [_score("2026-01-02", "000001.SZ", 82.0, 1.0)],
                        "risk_warnings": [],
                    }
                ),
                encoding="utf-8",
            )
            features.write_text(
                "symbol,trade_date,open,close,limit_up,limit_down,is_suspended\n"
                "000001.SZ,2026-01-02,9,9,false,false,false\n",
                encoding="utf-8",
            )
            account.write_text(
                json.dumps(
                    {
                        "cash": 90000.0,
                        "positions": {
                            "000001.SZ": {
                                "shares": 1000,
                                "cost_basis": 10.0,
                                "last_buy_date": "2025-12-01",
                            }
                        },
                        "nav_history": [],
                        "pending_targets": {"000001.SZ": 0.09},
                        "pending_signal_date": "2026-01-01",
                        "last_processed_date": "2026-01-01",
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_daily_paper_trading.py",
                    "--research-report",
                    str(research_report),
                    "--features",
                    str(features),
                    "--as-of",
                    "2026-01-02",
                    "--account",
                    str(account),
                    "--targets-output",
                    str(targets),
                    "--paper-report",
                    str(paper_report),
                    "--max-position-weight",
                    "0.10",
                    "--commission-rate",
                    "0",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )
            account_payload = json.loads(account.read_text(encoding="utf-8"))
            paper_payload = json.loads(paper_report.read_text(encoding="utf-8"))
            with targets.open(encoding="utf-8", newline="") as handle:
                target_rows = list(csv.DictReader(handle))

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        self.assertEqual(target_rows, [])
        self.assertEqual(account_payload["pending_targets"], {})
        self.assertEqual(
            paper_payload["target_risk_warnings"],
            [
                {
                    "action": "reduce",
                    "observed_value": 0.1,
                    "rule": "single_position_drawdown",
                    "symbol": "000001.SZ",
                    "threshold_value": 0.08,
                    "trade_date": "2026-01-02",
                }
            ],
        )

    def test_daily_paper_trading_records_scaled_target_without_double_scaling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            research_report = root / "run_report.json"
            features = root / "features.csv"
            account = root / "account.json"
            targets = root / "targets.csv"
            paper_report = root / "paper_report.json"
            research_report.write_text(
                json.dumps(
                    {
                        "scores": [_score("2026-01-02", "000001.SZ", 82.0, 1.0)],
                        "risk_warnings": [],
                    }
                ),
                encoding="utf-8",
            )
            features.write_text(
                "symbol,trade_date,close,limit_up,limit_down,is_suspended\n"
                "000001.SZ,2026-01-02,10,false,false,false\n",
                encoding="utf-8",
            )
            account.write_text(
                json.dumps(
                    {
                        "cash": 100000.0,
                        "positions": {},
                        "nav_history": [],
                        "shadow_cash": 100000.0,
                        "shadow_positions": {},
                        "shadow_nav_history": [],
                        "drawdown_control_state": {
                            "regime": "reduced",
                            "actual_peak": 100000.0,
                            "shadow_peak": 100000.0,
                            "last_transition_date": "2026-01-01",
                            "transitions": [],
                        },
                        "pending_targets": {"000001.SZ": 0.10},
                        "pending_signal_date": "2026-01-01",
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_daily_paper_trading.py",
                    "--research-report",
                    str(research_report),
                    "--features",
                    str(features),
                    "--as-of",
                    "2026-01-02",
                    "--account",
                    str(account),
                    "--targets-output",
                    str(targets),
                    "--paper-report",
                    str(paper_report),
                    "--max-position-weight",
                    "0.10",
                    "--commission-rate",
                    "0",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )
            account_payload = json.loads(account.read_text(encoding="utf-8"))
            with targets.open(encoding="utf-8", newline="") as handle:
                target_rows = list(csv.DictReader(handle))

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        self.assertEqual(target_rows[0]["raw_target_weight"], "0.1")
        self.assertEqual(target_rows[0]["target_weight"], "0.1")
        self.assertEqual(target_rows[0]["portfolio_exposure_multiplier"], "1.0")
        self.assertEqual(account_payload["positions"]["000001.SZ"]["shares"], 500)
        self.assertEqual(account_payload["shadow_positions"]["000001.SZ"]["shares"], 1000)

    def test_daily_paper_trading_generates_targets_and_runs_rebalance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            research_report = root / "run_report.json"
            features = root / "features.csv"
            account = root / "account.json"
            targets = root / "targets.csv"
            paper_report = root / "paper_report.json"
            research_report.write_text(
                json.dumps(
                    {
                        "scores": [
                            _score("2026-01-02", "000001.SZ", 82.0, 1.0),
                            _score("2026-01-02", "000002.SZ", 78.0, 1.0),
                            _score("2026-01-02", "000003.SZ", 91.0, 1.0),
                        ],
                        "risk_warnings": [
                            {
                                "trade_date": "2026-01-02",
                                "symbol": "000003.SZ",
                                "action": "reduce",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            features.write_text(
                "symbol,trade_date,close,limit_up,limit_down,is_suspended\n"
                "000001.SZ,2026-01-02,10,false,false,false\n"
                "000002.SZ,2026-01-02,20,false,false,false\n"
                "000003.SZ,2026-01-02,30,false,false,false\n",
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_daily_paper_trading.py",
                    "--research-report",
                    str(research_report),
                    "--features",
                    str(features),
                    "--as-of",
                    "2026-01-02",
                    "--account",
                    str(account),
                    "--targets-output",
                    str(targets),
                    "--paper-report",
                    str(paper_report),
                    "--buy-threshold",
                    "70",
                    "--min-score-confidence",
                    "0.8",
                    "--max-position-weight",
                    "0.10",
                    "--initial-cash",
                    "100000",
                    "--commission-rate",
                    "0",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            account_payload = json.loads(account.read_text(encoding="utf-8"))
            paper_payload = json.loads(paper_report.read_text(encoding="utf-8"))
            with targets.open(encoding="utf-8", newline="") as handle:
                target_rows = list(csv.DictReader(handle))

        self.assertIn("target_count=2", completed.stdout)
        self.assertIn("trade_count=0", completed.stdout)
        self.assertEqual([row["symbol"] for row in target_rows], ["000001.SZ", "000002.SZ"])
        self.assertEqual(account_payload["positions"], {})
        self.assertEqual(
            account_payload["pending_targets"],
            {"000001.SZ": 0.1, "000002.SZ": 0.1},
        )
        self.assertEqual(account_payload["pending_signal_date"], "2026-01-02")
        self.assertEqual(paper_payload["nav"]["equity"], 100000.0)

    def test_daily_paper_trading_can_use_dqn_report_as_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            research_report = root / "run_report.json"
            features = root / "features.csv"
            dqn_report = root / "dqn_report.json"
            account = root / "account.json"
            targets = root / "targets.csv"
            paper_report = root / "paper_report.json"
            research_report.write_text(
                json.dumps(
                    {
                        "scores": [
                            _score("2026-01-02", "000001.SZ", 82.0, 1.0),
                            _score("2026-01-02", "000002.SZ", 78.0, 1.0),
                            _score("2026-01-02", "000003.SZ", 75.0, 1.0),
                        ],
                        "risk_warnings": [],
                    }
                ),
                encoding="utf-8",
            )
            features.write_text(
                "symbol,trade_date,close,limit_up,limit_down,is_suspended\n"
                "000001.SZ,2026-01-02,10,false,false,false\n"
                "000002.SZ,2026-01-02,20,false,false,false\n"
                "000003.SZ,2026-01-02,10,false,false,false\n",
                encoding="utf-8",
            )
            dqn_report.write_text(
                json.dumps(
                    {
                        "strategy_config": {"symbols": ["000001.SZ", "000002.SZ", "000003.SZ"]},
                        "trades": [
                            {
                                "trade_date": "2026-01-01",
                                "symbol": "000001.SZ",
                                "action": "buy",
                                "position": 1,
                            },
                            {
                                "trade_date": "2026-01-02",
                                "symbol": "000002.SZ",
                                "action": "sell",
                                "position": 0,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_daily_paper_trading.py",
                    "--research-report",
                    str(research_report),
                    "--features",
                    str(features),
                    "--as-of",
                    "2026-01-02",
                    "--account",
                    str(account),
                    "--targets-output",
                    str(targets),
                    "--paper-report",
                    str(paper_report),
                    "--dqn-report",
                    str(dqn_report),
                    "--buy-threshold",
                    "70",
                    "--min-score-confidence",
                    "0.8",
                    "--max-position-weight",
                    "0.10",
                    "--initial-cash",
                    "100000",
                    "--commission-rate",
                    "0",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            with targets.open(encoding="utf-8", newline="") as handle:
                target_rows = list(csv.DictReader(handle))

        self.assertIn("target_count=3", completed.stdout)
        self.assertEqual(
            [(row["symbol"], row["target_weight"], row["rl_action"]) for row in target_rows],
            [
                ("000001.SZ", "0.1", "buy"),
                ("000002.SZ", "0.05", "hold"),
                ("000003.SZ", "0.05", "hold"),
            ],
        )


def _score(trade_date: str, symbol: str, total: float, confidence: float) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "symbol": symbol,
        "total": total,
        "confidence": confidence,
        "missing_fields": [],
    }


if __name__ == "__main__":
    unittest.main()
