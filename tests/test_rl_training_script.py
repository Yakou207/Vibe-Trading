from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


class RlTrainingScriptTest(unittest.TestCase):
    def test_random_policy_training_script_writes_episode_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            features_csv = tmp / "features.csv"
            output_json = tmp / "rl_random_policy_training.json"
            pd.DataFrame(
                {
                    "代码": ["sh688001", "sh688001", "sh688001"],
                    "date": ["2024-01-02", "2024-01-03", "2024-01-04"],
                    "close": [10.0, 11.0, 12.0],
                    "return_1d": [0.0, 0.1, 0.0909],
                }
            ).to_csv(features_csv, index=False)

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/train_rl_random_policy.py",
                    "--features-csv",
                    str(features_csv),
                    "--output",
                    str(output_json),
                    "--episodes",
                    "2",
                    "--seed",
                    "7",
                    "--initial-cash",
                    "10000",
                    "--target-weight",
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
            self.assertEqual(payload["policy"], "random")
            self.assertEqual(payload["episodes"], 2)
            self.assertEqual(len(payload["episode_results"]), 2)
            self.assertIn("total_reward", payload["episode_results"][0])


if __name__ == "__main__":
    unittest.main()
