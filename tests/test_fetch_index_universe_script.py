from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class FetchIndexUniverseScriptTest(unittest.TestCase):
    def test_fetch_index_universe_script_normalizes_csindex_csv_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "constituents.csv"
            output_path = root / "universe.csv"
            input_path.write_text(
                "日期,指数代码,指数名称,成分券代码,成分券名称,交易所,权重\n"
                "2026-06-30,000906,中证800,000001,平安银行,深圳证券交易所,0.246\n"
                "2026-06-30,000906,中证800,600000,浦发银行,上海证券交易所,0.215\n",
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/fetch_index_universe.py",
                    "--source",
                    "csv",
                    "--input",
                    str(input_path),
                    "--index-code",
                    "000906",
                    "--output",
                    str(output_path),
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

            with output_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        self.assertIn("member_count=2", completed.stdout)
        self.assertEqual(rows[0]["symbol"], "000001.SZ")
        self.assertEqual(rows[1]["symbol"], "600000.SH")
        self.assertEqual(rows[0]["index_code"], "000906")
        self.assertEqual(rows[0]["weight"], "0.246")


if __name__ == "__main__":
    unittest.main()
