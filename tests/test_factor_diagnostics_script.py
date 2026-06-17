from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


class FactorDiagnosticsScriptTest(unittest.TestCase):
    def test_script_writes_factor_diagnostics_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            features_csv = tmp / "features.csv"
            output_json = tmp / "factor_diagnostics_report.json"
            pd.DataFrame(
                {
                    "代码": ["sh688001", "sh688002", "sh688003"],
                    "date": ["2024-01-02", "2024-01-02", "2024-01-02"],
                    "rsi_14": [30.0, 50.0, 70.0],
                    "macd_hist": [-0.1, 0.0, 0.1],
                    "target_next_return_1d": [-0.01, 0.0, 0.02],
                }
            ).to_csv(features_csv, index=False)

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_factor_diagnostics_report.py",
                    "--features-csv",
                    str(features_csv),
                    "--output",
                    str(output_json),
                ],
                check=False,
                cwd=Path(__file__).resolve().parents[1],
                env={"PYTHONPATH": "src"},
                text=True,
                capture_output=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            self.assertEqual(payload["report"], "factor_diagnostics")
            self.assertGreaterEqual(payload["factor_count"], 2)
            self.assertIn("rsi_14", payload["factors"])


if __name__ == "__main__":
    unittest.main()
