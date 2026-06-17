from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


class QLearningScriptTest(unittest.TestCase):
    def test_script_writes_rl_vs_buy_hold_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            features_csv = tmp / "features.csv"
            output_json = tmp / "rl_vs_buy_hold_report.json"
            rows = []
            for date in pd.date_range("2020-01-01", "2023-12-31", freq="90D"):
                close = 10.0 + len(rows)
                rows.append(
                    {
                        "代码": "sh688001",
                        "date": date.date().isoformat(),
                        "open": close,
                        "close": close,
                        "volume": 1000,
                        "return_1d": 0.01,
                        "rsi_14": 80.0,
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
                    "scripts/run_walk_forward_q_learning.py",
                    "--features-csv",
                    str(features_csv),
                    "--output",
                    str(output_json),
                    "--episodes",
                    "2",
                    "--epsilon",
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
            self.assertEqual(payload["strategy"], "q_learning_v1")
            self.assertEqual(payload["baseline"], "equal_weight_buy_and_hold")
            self.assertEqual(len(payload["windows"]), 1)


if __name__ == "__main__":
    unittest.main()
