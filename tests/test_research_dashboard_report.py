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
                    "--output",
                    str(output),
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )
            html = output.read_text(encoding="utf-8")

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        self.assertIn("dashboard_path=", completed.stdout)
        self.assertIn("Daily Quant Monitor", html)
        self.assertIn("0.340000", html)
        self.assertIn("Paper NAV", html)


if __name__ == "__main__":
    unittest.main()
