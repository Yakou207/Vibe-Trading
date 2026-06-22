from __future__ import annotations

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
                        _bar("000001.SZ", "2026-01-01", 10.0),
                        _bar("000001.SZ", "2026-01-02", 11.0),
                        _bar("000001.SZ", "2026-01-03", 12.0),
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
            feature_text = feature_output.read_text(encoding="utf-8")

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("daily_rows=3", result.stdout)
            self.assertIn("feature_rows=3", result.stdout)
            self.assertIn("000001.SZ", daily_text)
            self.assertIn("return_1d", feature_text)
            self.assertIn("macd_positive", feature_text)


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
