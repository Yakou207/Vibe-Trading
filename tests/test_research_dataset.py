from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path


class ResearchDatasetTest(unittest.TestCase):
    def test_load_universe_csv_normalizes_symbols(self) -> None:
        from fintech_quant.data import load_universe_csv

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "universe.csv"
            path.write_text("symbol,name,sector\n000001,Ping An,Bank\n600000,SPDB,Bank\n", encoding="utf-8")

            universe = load_universe_csv(path)

        self.assertEqual([member.symbol for member in universe], ["000001.SZ", "600000.SH"])
        self.assertEqual(universe[0].name, "Ping An")
        self.assertEqual(universe[0].sector, "Bank")

    def test_collect_universe_history_calls_provider_once_per_symbol(self) -> None:
        from fintech_quant.data import UniverseMember, collect_universe_history

        class FakeProvider:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def history(self, symbol: str, start: date, end: date) -> list[dict[str, object]]:
                self.calls.append(symbol)
                return [
                    {
                        "symbol": symbol,
                        "trade_date": start.isoformat(),
                        "open": 10.0,
                        "high": 10.0,
                        "low": 10.0,
                        "close": 10.0,
                        "volume": 1000.0,
                        "amount": 10000.0,
                        "source": "fixture",
                    }
                ]

        provider = FakeProvider()
        rows = collect_universe_history(
            provider,
            [UniverseMember("000001.SZ"), UniverseMember("600000.SH")],
            date(2026, 1, 1),
            date(2026, 1, 2),
        )

        self.assertEqual(provider.calls, ["000001.SZ", "600000.SH"])
        self.assertEqual([row["symbol"] for row in rows], ["000001.SZ", "600000.SH"])

    def test_write_daily_and_feature_csv_outputs_stable_headers(self) -> None:
        from fintech_quant.data import write_daily_bars_csv, write_feature_rows_csv

        with tempfile.TemporaryDirectory() as tmp:
            daily_path = Path(tmp) / "daily.csv"
            feature_path = Path(tmp) / "features.csv"
            daily_rows = [
                {
                    "symbol": "000001.SZ",
                    "trade_date": "2026-01-01",
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.5,
                    "close": 10.5,
                    "volume": 1000.0,
                    "amount": 10500.0,
                    "source": "fixture",
                }
            ]
            feature_rows = [{**daily_rows[0], "return_1d": None, "ma20": None, "macd_positive": True}]

            write_daily_bars_csv(daily_path, daily_rows)
            write_feature_rows_csv(feature_path, feature_rows)

            with daily_path.open("r", encoding="utf-8", newline="") as handle:
                daily = list(csv.DictReader(handle))
            with feature_path.open("r", encoding="utf-8", newline="") as handle:
                features = list(csv.DictReader(handle))

        self.assertEqual(list(daily[0]), ["symbol", "trade_date", "open", "high", "low", "close", "volume", "amount", "source"])
        self.assertEqual(daily[0]["symbol"], "000001.SZ")
        self.assertIn("return_1d", features[0])
        self.assertIn("macd_positive", features[0])

    def test_write_feature_csv_keeps_standard_headers_when_empty(self) -> None:
        from fintech_quant.data import write_feature_rows_csv

        with tempfile.TemporaryDirectory() as tmp:
            feature_path = Path(tmp) / "features.csv"

            write_feature_rows_csv(feature_path, [])

            header = feature_path.read_text(encoding="utf-8").splitlines()[0].split(",")

        self.assertIn("return_1d", header)
        self.assertIn("ma20", header)
        self.assertIn("rsi14", header)
        self.assertIn("macd_line", header)
        self.assertIn("volatility20", header)


if __name__ == "__main__":
    unittest.main()
