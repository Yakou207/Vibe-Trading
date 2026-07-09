from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


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

    def test_fetch_market_state_falls_back_to_csindex_for_csi300(self) -> None:
        from scripts.fetch_market_state import _bars_from_akshare

        fake_akshare = _FakeAkShareIndexModule()

        with patch("scripts.fetch_market_state.importlib.import_module", return_value=fake_akshare):
            bars = _bars_from_akshare(
                "sh000300",
                date.fromisoformat("2021-06-16"),
                date.fromisoformat("2026-06-16"),
            )

        self.assertTrue(fake_akshare.em_called)
        self.assertTrue(fake_akshare.csindex_called)
        self.assertEqual(bars[0].trade_date.isoformat(), "2021-06-16")
        self.assertEqual(bars[0].close, 5080.49)

    def test_fetch_market_state_reads_own_index_close_csv_output(self) -> None:
        from scripts.fetch_market_state import _bars_from_csv

        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "market_state.csv"
            input_path.write_text(
                "trade_date,index_symbol,index_close,index_ma250,index_below_annual_ma\n"
                "2026-01-01,sh000001,100,99,false\n",
                encoding="utf-8",
            )

            bars = _bars_from_csv(input_path)

        self.assertEqual(bars[0].trade_date.isoformat(), "2026-01-01")
        self.assertEqual(bars[0].close, 100.0)

class _FakeAkShareIndexModule:
    def __init__(self) -> None:
        self.em_called = False
        self.csindex_called = False

    def stock_zh_index_daily_em(self, **_kwargs: object) -> object:
        self.em_called = True
        raise RuntimeError("eastmoney unavailable")

    def stock_zh_index_hist_csindex(self, **kwargs: object) -> object:
        self.csindex_called = True
        if kwargs != {"symbol": "000300", "start_date": "20210616", "end_date": "20260616"}:
            raise AssertionError(kwargs)
        return _FakeFrame([{"日期": "2021-06-16", "收盘": 5080.49}])


class _FakeFrame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        if orient != "records":
            raise AssertionError(orient)
        return self._rows


if __name__ == "__main__":
    unittest.main()
