from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class FetchMarketStateScriptTest(unittest.TestCase):
    def test_fetch_market_state_builds_index_annual_ma_flags_from_csv_fixture(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "index.csv"
            output_path = root / "market_state.csv"
            input_path.write_text(
                "date,close\n"
                "2026-01-01,100\n"
                "2026-01-02,102\n"
                "2026-01-03,101\n"
                "2026-01-04,99\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/fetch_market_state.py",
                    "--source",
                    "csv",
                    "--input",
                    str(input_path),
                    "--start",
                    "2026-01-03",
                    "--end",
                    "2026-01-04",
                    "--output",
                    str(output_path),
                    "--ma-window",
                    "3",
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertEqual(result.stdout.strip(), "stored_market_state_rows=2")
            self.assertEqual(
                output_path.read_text(encoding="utf-8").strip().splitlines(),
                [
                    "trade_date,index_symbol,index_close,index_ma250,index_below_annual_ma",
                    "2026-01-03,sh000001,101.0,101.0,false",
                    "2026-01-04,sh000001,99.0,100.666667,true",
                ],
            )


if __name__ == "__main__":
    unittest.main()
