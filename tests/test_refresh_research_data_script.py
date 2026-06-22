from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class RefreshResearchDataScriptTest(unittest.TestCase):
    def test_refresh_script_writes_daily_and_feature_outputs_from_json_fixture(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            universe_path = tmp_path / "universe.csv"
            input_path = tmp_path / "bars.json"
            daily_output = tmp_path / "daily.csv"
            feature_output = tmp_path / "features.csv"
            universe_path.write_text("symbol,name,sector\n000001,Ping An,Bank\n", encoding="utf-8")
            input_path.write_text(
                json.dumps(
                    [
                        _bar("000001", "2026-01-03", 12.0),
                        _bar("000001", "2026-01-01", 10.0),
                        _bar("000001", "2026-01-02", 11.0),
                    ],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/refresh_research_data.py",
                    "--source",
                    "json",
                    "--input",
                    str(input_path),
                    "--universe",
                    str(universe_path),
                    "--daily-output",
                    str(daily_output),
                    "--feature-output",
                    str(feature_output),
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            daily_text = daily_output.read_text(encoding="utf-8")
            with feature_output.open("r", encoding="utf-8", newline="") as handle:
                feature_rows = list(csv.DictReader(handle))

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("daily_rows=3", result.stdout)
            self.assertIn("feature_rows=3", result.stdout)
            self.assertIn("000001.SZ", daily_text)
            self.assertLess(daily_text.index("2026-01-01"), daily_text.index("2026-01-03"))
            self.assertEqual(list(feature_rows[0]), [
                "symbol",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "source",
                "return_1d",
                "ma20",
                "ma60",
                "ma250",
                "close_above_ma20",
                "close_above_ma60",
                "close_above_ma250",
                "rsi14",
                "macd_line",
                "macd_signal",
                "macd_hist",
                "macd_positive",
                "volatility20",
            ])


def _bar(symbol: str, trade_date: str, close: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1000.0,
        "amount": close * 1000.0,
        "source": "fixture",
    }


if __name__ == "__main__":
    unittest.main()
