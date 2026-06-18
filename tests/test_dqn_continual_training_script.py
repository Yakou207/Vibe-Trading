from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


class DQNContinualTrainingScriptTest(unittest.TestCase):
    def test_script_saves_checkpoint_and_resumes_latest_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            features_csv = tmp / "features.csv"
            checkpoint_root = tmp / "models" / "dqn"
            _dqn_training_frame().to_csv(features_csv, index=False)

            first = subprocess.run(
                [
                    sys.executable,
                    "training/run_dqn_continual_training.py",
                    "--features-csv",
                    str(features_csv),
                    "--checkpoint-root",
                    str(checkpoint_root),
                    "--checkpoint-id",
                    "run_001",
                    "--episodes",
                    "1",
                    "--batch-size",
                    "2",
                    "--replay-capacity",
                    "8",
                    "--max-checkpoints",
                    "2",
                    "--fresh",
                ],
                check=False,
                cwd=Path(__file__).resolve().parents[1],
                env={"PYTHONPATH": "src"},
                text=True,
                capture_output=True,
            )

            self.assertEqual(first.returncode, 0, first.stderr)
            manifest = json.loads((checkpoint_root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["latest"], "run_001")
            self.assertTrue((checkpoint_root / "checkpoints" / "run_001" / "model.pt").exists())

            second = subprocess.run(
                [
                    sys.executable,
                    "training/run_dqn_continual_training.py",
                    "--features-csv",
                    str(features_csv),
                    "--checkpoint-root",
                    str(checkpoint_root),
                    "--checkpoint-id",
                    "run_002",
                    "--episodes",
                    "1",
                    "--batch-size",
                    "2",
                    "--replay-capacity",
                    "8",
                    "--max-checkpoints",
                    "2",
                    "--resume",
                    "latest",
                ],
                check=False,
                cwd=Path(__file__).resolve().parents[1],
                env={"PYTHONPATH": "src"},
                text=True,
                capture_output=True,
            )

            self.assertEqual(second.returncode, 0, second.stderr)
            manifest = json.loads((checkpoint_root / "manifest.json").read_text(encoding="utf-8"))
            state = json.loads(
                (
                    checkpoint_root
                    / "checkpoints"
                    / "run_002"
                    / "training_state.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["latest"], "run_002")
            self.assertEqual(state["episodes_trained"], 2)
            self.assertGreater(state["replay_size"], 0)


def _dqn_training_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "代码": ["sh688001"] * 5,
            "date": [
                "2024-01-02",
                "2024-01-03",
                "2024-01-04",
                "2024-01-05",
                "2024-01-08",
            ],
            "open": [10.0, 10.5, 11.0, 10.8, 11.2],
            "high": [10.2, 10.7, 11.2, 11.0, 11.4],
            "low": [9.8, 10.3, 10.8, 10.6, 11.0],
            "close": [10.0, 10.5, 11.0, 10.8, 11.2],
            "volume": [1000, 1000, 1000, 1000, 1000],
            "return_1d": [0.0, 0.05, 0.0476, -0.0182, 0.0370],
            "rsi_14": [45.0, 55.0, 65.0, 50.0, 48.0],
            "macd_hist": [0.1, 0.2, 0.1, -0.1, 0.05],
            "return_5d": [0.01, 0.02, 0.03, -0.01, 0.02],
            "return_20d": [0.01, 0.02, 0.03, -0.01, 0.02],
            "close_to_ma_20": [1.0, 1.01, 1.02, 0.99, 1.01],
            "ma_20_slope": [0.01, 0.01, 0.02, 0.0, 0.01],
            "volatility_20": [0.02, 0.02, 0.03, 0.03, 0.02],
            "target_next_return_1d": [0.05, 0.04, -0.02, 0.03, 0.0],
        }
    )


if __name__ == "__main__":
    unittest.main()
