from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class GenerateStrategyTargetsScriptTest(unittest.TestCase):
    def test_generate_strategy_targets_uses_scores_risk_and_rl_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "run_report.json"
            rl_signals_path = root / "rl_signals.csv"
            output_path = root / "targets.csv"
            report_path.write_text(
                json.dumps(
                    {
                        "scores": [
                            _score("2026-01-02", "000001.SZ", 82.0, 1.0),
                            _score("2026-01-02", "000002.SZ", 78.0, 1.0),
                            _score("2026-01-02", "000003.SZ", 91.0, 1.0),
                            _score("2026-01-02", "000004.SZ", 65.0, 1.0),
                        ],
                        "risk_warnings": [
                            {
                                "trade_date": "2026-01-02",
                                "symbol": "000003.SZ",
                                "action": "reduce",
                                "rule": "portfolio_drawdown",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            rl_signals_path.write_text(
                "symbol,trade_date,rl_action\n"
                "000001.SZ,2026-01-02,hold\n"
                "000002.SZ,2026-01-02,sell\n",
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/generate_strategy_targets.py",
                    "--report",
                    str(report_path),
                    "--as-of",
                    "2026-01-02",
                    "--output",
                    str(output_path),
                    "--buy-threshold",
                    "70",
                    "--min-score-confidence",
                    "0.8",
                    "--max-position-weight",
                    "0.08",
                    "--rl-signals",
                    str(rl_signals_path),
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )
            with output_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        self.assertIn("target_count=1", completed.stdout)
        self.assertEqual(rows[0]["symbol"], "000001.SZ")
        self.assertEqual(rows[0]["target_weight"], "0.04")
        self.assertEqual(rows[0]["rl_action"], "hold")


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
