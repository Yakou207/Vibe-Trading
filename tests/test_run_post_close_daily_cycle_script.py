from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class RunPostCloseDailyCycleScriptTest(unittest.TestCase):
    def test_post_close_cycle_leaves_canonical_account_unchanged_when_dashboard_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            research_report = root / "run_report.json"
            features = root / "features.csv"
            comparison = root / "comparison.json"
            account = root / "account.json"
            targets = root / "targets.csv"
            paper_report = root / "paper_report.json"
            dashboard = root / "dashboard.html"
            cycle_manifest = root / "cycle_manifest.json"
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
            comparison.write_text("{\n", encoding="utf-8")
            account.write_text(
                json.dumps(
                    {
                        "cash": 100000.0,
                        "positions": {},
                        "nav_history": [],
                        "pending_targets": {},
                        "pending_signal_date": None,
                        "last_processed_date": "2026-01-01",
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            account_before = account.read_bytes()

            completed = _run_cycle(
                research_report=research_report,
                features=features,
                comparison=comparison,
                account=account,
                targets=targets,
                paper_report=paper_report,
                dashboard=dashboard,
                cycle_manifest=cycle_manifest,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(account.read_bytes(), account_before)
            self.assertFalse(targets.exists())
            self.assertFalse(paper_report.exists())
            self.assertFalse(dashboard.exists())
            self.assertFalse(cycle_manifest.exists())

    def test_post_close_cycle_runs_paper_trading_and_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            research_report = root / "run_report.json"
            features = root / "features.csv"
            comparison = root / "comparison.json"
            dqn_report = root / "dqn_report.json"
            walk_forward = root / "walk_forward.json"
            account = root / "account.json"
            targets = root / "targets.csv"
            paper_report = root / "paper_report.json"
            dashboard = root / "dashboard.html"
            cycle_manifest = root / "cycle_manifest.json"
            research_report.write_text(
                json.dumps(
                    {
                        "date_range": ["2026-01-01", "2026-01-02"],
                        "scores": [
                            _score("2026-01-02", "000001.SZ", 82.0, 1.0),
                            _score("2026-01-02", "000002.SZ", 78.0, 1.0),
                        ],
                        "risk_warnings": [],
                        "risk_summary": {"total_warnings": 0, "by_rule": {}},
                    }
                ),
                encoding="utf-8",
            )
            features.write_text(
                "symbol,trade_date,close,limit_up,limit_down,is_suspended\n"
                "000001.SZ,2026-01-02,10,false,false,false\n"
                "000002.SZ,2026-01-02,20,false,false,false\n",
                encoding="utf-8",
            )
            comparison.write_text(
                json.dumps(
                    {
                        "candidate": {"name": "dqn", "total_return": 0.02},
                        "baseline": {"name": "baseline", "total_return": 0.01},
                        "candidate_vs_benchmark": {
                            "csi300": {"excess_return": 0.015, "tracking_max_drawdown": 0.03}
                        },
                    }
                ),
                encoding="utf-8",
            )
            dqn_report.write_text(
                json.dumps(
                    {
                        "strategy_config": {"symbols": ["000001.SZ", "000002.SZ"]},
                        "trades": [
                            {
                                "trade_date": "2026-01-01",
                                "symbol": "000001.SZ",
                                "action": "buy",
                                "position": 1,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            walk_forward.write_text(
                json.dumps({"summary": {"window_count": 1, "mean_total_return": 0.02}}),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_post_close_daily_cycle.py",
                    "--as-of",
                    "2026-01-02",
                    "--research-report",
                    str(research_report),
                    "--features",
                    str(features),
                    "--comparison",
                    str(comparison),
                    "--dqn-report",
                    str(dqn_report),
                    "--walk-forward",
                    str(walk_forward),
                    "--account",
                    str(account),
                    "--targets-output",
                    str(targets),
                    "--paper-report",
                    str(paper_report),
                    "--dashboard-output",
                    str(dashboard),
                    "--cycle-manifest",
                    str(cycle_manifest),
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
                    "--minimum-commission",
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
            paper_payload = json.loads(paper_report.read_text(encoding="utf-8"))
            cycle_payload = json.loads(cycle_manifest.read_text(encoding="utf-8"))
            account_sha256 = hashlib.sha256(account.read_bytes()).hexdigest()
            dashboard_html = dashboard.read_text(encoding="utf-8")

            second = subprocess.run(
                completed.args,
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertIn("paper_report_path=", completed.stdout)
        self.assertIn("dashboard_path=", completed.stdout)
        self.assertEqual(
            [(row["symbol"], row["target_weight"], row["rl_action"]) for row in target_rows],
            [("000001.SZ", "0.1", "buy"), ("000002.SZ", "0.05", "hold")],
        )
        self.assertEqual(paper_payload["nav"]["equity"], 100000.0)
        self.assertEqual(cycle_payload["as_of"], "2026-01-02")
        self.assertEqual(
            cycle_payload["account_after_sha256"],
            account_sha256,
        )
        self.assertIn("Daily Quant Monitor", dashboard_html)
        self.assertIn("Paper NAV", dashboard_html)
        self.assertIn("0.015000", dashboard_html)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertIn("already_completed=true", second.stdout)


def _run_cycle(
    *,
    research_report: Path,
    features: Path,
    comparison: Path,
    account: Path,
    targets: Path,
    paper_report: Path,
    dashboard: Path,
    cycle_manifest: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/run_post_close_daily_cycle.py",
            "--as-of",
            "2026-01-02",
            "--research-report",
            str(research_report),
            "--features",
            str(features),
            "--comparison",
            str(comparison),
            "--account",
            str(account),
            "--targets-output",
            str(targets),
            "--paper-report",
            str(paper_report),
            "--dashboard-output",
            str(dashboard),
            "--cycle-manifest",
            str(cycle_manifest),
            "--initial-cash",
            "100000",
            "--commission-rate",
            "0",
            "--minimum-commission",
            "0",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
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
