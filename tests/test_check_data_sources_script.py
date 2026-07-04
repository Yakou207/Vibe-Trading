from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


class CheckDataSourcesScriptTest(unittest.TestCase):
    def test_check_data_sources_can_check_every_symbol_in_universe(self) -> None:
        worktree = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_modules = root / "fake_modules"
            fake_modules.mkdir()
            universe_path = root / "universe.csv"
            output_path = root / "source_health.json"
            _write_fake_akshare(fake_modules / "akshare.py")
            universe_path.write_text("symbol,name,sector\n000001,平安银行,银行\n600000,浦发银行,银行\n", encoding="utf-8")

            env = dict(os.environ)
            env["PYTHONPATH"] = str(fake_modules)

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/check_data_sources.py",
                    "--checks",
                    "akshare_daily",
                    "--universe",
                    str(universe_path),
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-01-02",
                    "--output",
                    str(output_path),
                    "--strict",
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["symbols"], ["000001.SZ", "600000.SH"])
        self.assertEqual(payload["summary"], {"ok": 2, "failed": 0, "skipped": 0})
        self.assertEqual(
            [(check["name"], check["symbol"], check["status"]) for check in payload["checks"]],
            [
                ("akshare_daily", "000001.SZ", "ok"),
                ("akshare_daily", "600000.SH", "ok"),
            ],
        )

    def test_check_data_sources_reports_akshare_and_tushare_smoke_status(self) -> None:
        worktree = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_modules = root / "fake_modules"
            fake_modules.mkdir()
            output_path = root / "source_health.json"
            _write_fake_akshare(fake_modules / "akshare.py")
            _write_fake_tushare(fake_modules / "tushare.py")

            env = dict(os.environ)
            env["PYTHONPATH"] = str(fake_modules)
            env["TUSHARE_TOKEN"] = "fixture-token"

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/check_data_sources.py",
                    "--checks",
                    "akshare_daily,akshare_realtime,akshare_fundamental,tushare_daily,tushare_fundamental",
                    "--symbol",
                    "000001",
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-01-02",
                    "--output",
                    str(output_path),
                    "--strict",
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn(f"source_health_path={output_path}", result.stdout)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["summary"], {"ok": 5, "failed": 0, "skipped": 0})
        statuses = {check["name"]: check for check in payload["checks"]}
        self.assertEqual(statuses["akshare_daily"]["row_count"], 1)
        self.assertIn("close", statuses["akshare_daily"]["fields"])
        self.assertEqual(statuses["akshare_realtime"]["row_count"], 1)
        self.assertIn("price", statuses["akshare_realtime"]["fields"])
        self.assertEqual(statuses["akshare_fundamental"]["row_count"], 1)
        self.assertEqual(statuses["tushare_daily"]["row_count"], 1)
        self.assertEqual(statuses["tushare_fundamental"]["row_count"], 1)

    def test_check_data_sources_skips_tushare_without_token_unless_strict(self) -> None:
        worktree = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_path = root / "source_health.json"
            env = dict(os.environ)
            env.pop("PYTHONPATH", None)
            env.pop("TUSHARE_TOKEN", None)

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/check_data_sources.py",
                    "--checks",
                    "tushare_daily",
                    "--symbol",
                    "000001",
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-01-02",
                    "--output",
                    str(output_path),
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["summary"], {"ok": 0, "failed": 0, "skipped": 1})
        self.assertEqual(payload["checks"][0]["status"], "skipped")
        self.assertIn("TUSHARE_TOKEN", payload["checks"][0]["message"])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            strict_output_path = root / "source_health_strict.json"
            env = dict(os.environ)
            env.pop("PYTHONPATH", None)
            env.pop("TUSHARE_TOKEN", None)

            strict_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/check_data_sources.py",
                    "--checks",
                    "tushare_daily",
                    "--symbol",
                    "000001",
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-01-02",
                    "--output",
                    str(strict_output_path),
                    "--strict",
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            strict_payload = json.loads(strict_output_path.read_text(encoding="utf-8"))

        self.assertEqual(strict_result.returncode, 1)
        self.assertEqual(strict_payload["summary"], {"ok": 0, "failed": 0, "skipped": 1})
        self.assertEqual(strict_payload["checks"][0]["status"], "skipped")


def _write_fake_akshare(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            """
            class Frame:
                def __init__(self, rows):
                    self._rows = rows

                def to_dict(self, orient):
                    assert orient == "records"
                    return self._rows


            def stock_zh_a_hist(symbol, period, start_date, end_date, adjust):
                return Frame([
                    {
                        "日期": "2026-01-02",
                        "开盘": 10,
                        "最高": 11,
                        "最低": 9,
                        "收盘": 10.5,
                        "成交量": 1000,
                        "成交额": 10500,
                    }
                ])


            def stock_zh_a_spot_em():
                return Frame([
                    {
                        "代码": "000001",
                        "名称": "平安银行",
                        "最新价": 10.5,
                        "涨跌幅": 1.2,
                        "涨跌额": 0.12,
                        "成交量": 1000,
                        "成交额": 10500,
                        "换手率": 0.3,
                        "市盈率-动态": 8.5,
                        "市净率": 0.9,
                    }
                ])


            def stock_a_indicator_lg(symbol):
                return Frame([{"trade_date": "2026-01-02", "pe": 8.5, "pb": 0.9}])


            def stock_financial_analysis_indicator(symbol):
                return Frame([{"日期": "2026-01-02", "净资产收益率": 15.0, "主营业务收入增长率": 12.0}])
            """
        ),
        encoding="utf-8",
    )


def _write_fake_tushare(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            """
            class Frame:
                def __init__(self, rows):
                    self._rows = rows

                def to_dict(self, orient):
                    assert orient == "records"
                    return self._rows


            class Pro:
                def daily(self, ts_code, start_date, end_date):
                    return Frame([
                        {
                            "trade_date": "20260102",
                            "open": 10,
                            "high": 11,
                            "low": 9,
                            "close": 10.5,
                            "vol": 1000,
                            "amount": 10500,
                        }
                    ])

                def daily_basic(self, ts_code, start_date, end_date):
                    return Frame([{"trade_date": "20260102", "pe": 8.5, "pb": 0.9}])

                def fina_indicator(self, ts_code, start_date, end_date):
                    return Frame([{"end_date": "20260102", "roe": 15.0, "or_yoy": 12.0}])


            def pro_api(token):
                return Pro()
            """
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
