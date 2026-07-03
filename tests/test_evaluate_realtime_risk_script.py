from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class EvaluateRealtimeRiskScriptTest(unittest.TestCase):
    def test_realtime_risk_script_flags_systemic_drop_count(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quotes_path = root / "quotes.csv"
            output_path = root / "risk.json"
            with quotes_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("symbol", "change_pct", "price", "source"))
                writer.writeheader()
                for index in range(16):
                    writer.writerow(
                        {
                            "symbol": f"0000{index + 1:02d}.SZ",
                            "change_pct": "-0.031",
                            "price": "10.0",
                            "source": "fixture",
                        }
                    )
                writer.writerow({"symbol": "000099.SZ", "change_pct": "-0.03", "price": "9.0", "source": "fixture"})
                writer.writerow({"symbol": "000100.SZ", "change_pct": "", "price": "9.0", "source": "fixture"})
                writer.writerow({"symbol": "600000.SH", "change_pct": "0.01", "price": "8.0", "source": "fixture"})

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/evaluate_realtime_risk.py",
                    "--quotes",
                    str(quotes_path),
                    "--output",
                    str(output_path),
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("risk_action=reduce", result.stdout)
        self.assertIn("valid_quote_rows=18", result.stdout)
        self.assertIn("skipped_quote_rows=1", result.stdout)
        self.assertEqual(payload["risk_input"]["broad_market_drop_gt_3pct_count"], 16)
        self.assertEqual(payload["valid_quote_rows"], 18)
        self.assertEqual(payload["skipped_quote_rows"], 1)
        self.assertEqual(payload["action"], "reduce")
        self.assertEqual(payload["warnings"][0]["rule"], "broad_market_drop_gt_3pct_count")


if __name__ == "__main__":
    unittest.main()
