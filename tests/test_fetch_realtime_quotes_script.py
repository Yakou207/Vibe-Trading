from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class FetchRealtimeQuotesScriptTest(unittest.TestCase):
    def test_fetch_realtime_quotes_writes_filtered_quotes_from_json_fixture(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "quotes.json"
            output_path = root / "quotes.csv"
            input_path.write_text(
                json.dumps(
                    [
                        _quote("000001", "平安银行", 10.5),
                        _quote("600000", "浦发银行", 8.0),
                    ],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/fetch_realtime_quotes.py",
                    "--source",
                    "json",
                    "--input",
                    str(input_path),
                    "--symbols",
                    "000001",
                    "--output",
                    str(output_path),
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            with output_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("quote_rows=1", result.stdout)
        self.assertEqual(rows[0]["symbol"], "000001.SZ")
        self.assertEqual(rows[0]["price"], "10.5")
        self.assertEqual(rows[0]["source"], "json")


def _quote(symbol: str, name: str, price: float) -> dict[str, object]:
    return {
        "代码": symbol,
        "名称": name,
        "最新价": price,
        "涨跌幅": 1.2,
        "涨跌额": 0.12,
        "成交量": 12345,
        "成交额": 678900,
    }


if __name__ == "__main__":
    unittest.main()
