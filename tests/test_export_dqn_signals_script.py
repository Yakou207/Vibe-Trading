from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ExportDqnSignalsScriptTest(unittest.TestCase):
    def test_export_dqn_signals_writes_daily_overlay_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "dqn_report.json"
            output_path = root / "rl_signals.csv"
            report_path.write_text(
                json.dumps(
                    {
                        "strategy_config": {
                            "policy": "linear_q_dqn_v0",
                            "symbols": ["000001.SZ", "000002.SZ", "000003.SZ"],
                        },
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
                                "action": "buy",
                                "position": 1,
                            },
                            {
                                "trade_date": "2026-01-03",
                                "symbol": "000002.SZ",
                                "action": "sell",
                                "position": 0,
                            },
                            {
                                "trade_date": "2026-01-04",
                                "symbol": "000001.SZ",
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
                    "scripts/export_dqn_signals.py",
                    "--report",
                    str(report_path),
                    "--as-of",
                    "2026-01-03",
                    "--output",
                    str(output_path),
                    "--flat-action",
                    "sell",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            with output_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertIn("signal_count=3", completed.stdout)
        self.assertEqual(
            [(row["symbol"], row["rl_action"]) for row in rows],
            [("000001.SZ", "buy"), ("000002.SZ", "sell"), ("000003.SZ", "hold")],
        )
        self.assertEqual(rows[0]["source_trade_date"], "2026-01-01")
        self.assertEqual(rows[1]["source_trade_date"], "2026-01-03")
        self.assertEqual(rows[2]["source_trade_date"], "")

    def test_export_dqn_signals_defaults_flat_positions_to_hold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "dqn_report.json"
            output_path = root / "rl_signals.csv"
            report_path.write_text(
                json.dumps(
                    {
                        "strategy_config": {"symbols": ["000001.SZ"]},
                        "trades": [
                            {
                                "trade_date": "2026-01-02",
                                "symbol": "000001.SZ",
                                "action": "sell",
                                "position": 0,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/export_dqn_signals.py",
                    "--report",
                    str(report_path),
                    "--as-of",
                    "2026-01-03",
                    "--output",
                    str(output_path),
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            with output_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(rows[0]["rl_action"], "hold")


if __name__ == "__main__":
    unittest.main()
