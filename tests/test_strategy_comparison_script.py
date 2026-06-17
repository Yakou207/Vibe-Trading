from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


class StrategyComparisonScriptTest(unittest.TestCase):
    def test_script_writes_strategy_comparison_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            features_csv = tmp / "features.csv"
            output_json = tmp / "strategy_comparison_report.json"
            rows = []
            for date in pd.date_range("2020-01-01", "2023-12-31", freq="90D"):
                index = len(rows)
                rows.append(
                    {
                        "代码": "sh688001",
                        "date": date.date().isoformat(),
                        "close": 10.0 + index,
                        "rsi_14": 45.0,
                        "macd_hist": 0.2,
                        "return_5d": 0.1,
                        "volatility_20": 0.01,
                        "target_next_return_1d": 0.05,
                    }
                )
            pd.DataFrame(rows).to_csv(features_csv, index=False)

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_strategy_comparison_report.py",
                    "--features-csv",
                    str(features_csv),
                    "--output",
                    str(output_json),
                    "--episodes",
                    "2",
                    "--dqn-episodes",
                    "1",
                    "--dqn-batch-size",
                    "2",
                    "--epsilon",
                    "0",
                    "--dqn-epsilon",
                    "0",
                    "--train-years",
                    "2",
                    "--test-years",
                    "1",
                    "--initial-cash",
                    "10000",
                    "--target-weight",
                    "0.5",
                    "--max-position-weight",
                    "0.6",
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
            self.assertEqual(payload["report"], "strategy_comparison_diagnostics")
            self.assertEqual(len(payload["windows"]), 1)
            self.assertIn("dqn", payload)
            self.assertIn("dqn_v1", payload["windows"][0]["strategies"])


if __name__ == "__main__":
    unittest.main()
