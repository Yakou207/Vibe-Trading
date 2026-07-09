from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ResearchDashboardReportTest(unittest.TestCase):
    def test_build_research_dashboard_writes_monitoring_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            comparison = root / "comparison.json"
            walk_forward = root / "walk_forward.json"
            paper = root / "paper.json"
            run_report = root / "run_report.json"
            data_health = root / "data_health.json"
            information_health = root / "information_health.json"
            output = root / "dashboard.html"
            comparison.write_text(
                json.dumps(
                    {
                        "candidate": {"name": "dqn", "total_return": 0.7, "max_drawdown": 0.1},
                        "baseline": {"name": "baseline", "total_return": 0.0, "max_drawdown": 0.0},
                        "candidate_vs_benchmark": {
                            "sse": {"excess_return": 0.34, "tracking_max_drawdown": 0.12},
                            "csi300": {"excess_return": 0.32, "tracking_max_drawdown": 0.16},
                        },
                    }
                ),
                encoding="utf-8",
            )
            walk_forward.write_text(json.dumps({"summary": {"window_count": 3, "mean_total_return": 0.03}}), encoding="utf-8")
            paper.write_text(json.dumps({"nav": {"equity": 101000.0}, "trades": [{}], "blocked_orders": []}), encoding="utf-8")
            run_report.write_text(
                json.dumps(
                    {
                        "date_range": ["2026-01-01", "2026-01-02"],
                        "summary": {"risk_warning_count": 2},
                        "risk_summary": {
                            "total_warnings": 2,
                            "by_rule": {"portfolio_drawdown": 1, "main_outflow_days": 1},
                        },
                        "risk_warnings": [
                            {"trade_date": "2026-01-02", "symbol": "000001.SZ", "rule": "portfolio_drawdown", "action": "reduce"},
                            {"trade_date": "2026-01-02", "symbol": "000002.SZ", "rule": "main_outflow_days", "action": "watch"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            data_health.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-01-02T09:00:00+00:00",
                        "end": "2026-01-02",
                        "summary": {"ok": 5, "failed": 1, "skipped": 0},
                    }
                ),
                encoding="utf-8",
            )
            information_health.write_text(
                json.dumps({"summary": {"ok_sources": 4, "error_sources": 0, "total_records": 8}}),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_research_dashboard.py",
                    "--comparison",
                    str(comparison),
                    "--walk-forward",
                    str(walk_forward),
                    "--paper-report",
                    str(paper),
                    "--run-report",
                    str(run_report),
                    "--data-health",
                    str(data_health),
                    "--information-health",
                    str(information_health),
                    "--output",
                    str(output),
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            html = output.read_text(encoding="utf-8")

        self.assertIn("dashboard_path=", completed.stdout)
        self.assertIn("Daily Quant Monitor", html)
        self.assertIn("0.340000", html)
        self.assertIn("Paper NAV", html)
        self.assertIn("Data End", html)
        self.assertIn("2026-01-02", html)
        self.assertIn("Data Checks", html)
        self.assertIn("5 ok / 1 failed / 0 skipped", html)
        self.assertIn("Information Sources", html)
        self.assertIn("4 ok / 0 errors / 8 records", html)
        self.assertIn("Risk Warnings", html)
        self.assertIn("portfolio_drawdown", html)
        self.assertIn("Mean WF Return", html)
        self.assertIn("0.030000", html)


if __name__ == "__main__":
    unittest.main()
