from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


class BacktestBaselineScriptTest(unittest.TestCase):
    def test_script_writes_baseline_backtest_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            features_csv = tmp / "features.csv"
            output_json = tmp / "baseline_backtest.json"
            pd.DataFrame(
                {
                    "代码": ["sh688001", "sh688002", "sh688001", "sh688002"],
                    "date": ["2024-01-02", "2024-01-02", "2024-01-03", "2024-01-03"],
                    "close": [10.0, 20.0, 11.0, 19.0],
                }
            ).to_csv(features_csv, index=False)

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_backtest_baseline.py",
                    "--features-csv",
                    str(features_csv),
                    "--output",
                    str(output_json),
                    "--initial-cash",
                    "10000",
                    "--target-weight",
                    "0.45",
                    "--max-position-weight",
                    "0.5",
                    "--commission-rate",
                    "0",
                    "--stamp-tax-rate",
                    "0",
                    "--slippage-rate",
                    "0",
                ],
                check=False,
                cwd=Path(__file__).resolve().parents[1],
                env={"PYTHONPATH": "src"},
                text=True,
                capture_output=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            self.assertEqual(payload["strategy"], "equal_weight_buy_and_hold")
            self.assertEqual(payload["metrics"]["trade_count"], 2)
            self.assertEqual(payload["metrics"]["final_equity"], 10200.0)
            self.assertEqual(len(payload["equity_curve"]), 2)


if __name__ == "__main__":
    unittest.main()
