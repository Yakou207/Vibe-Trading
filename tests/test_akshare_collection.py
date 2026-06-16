from __future__ import annotations

import unittest
from datetime import date


class AkShareCollectionTest(unittest.TestCase):
    def test_selects_30_star_market_symbols_by_turnover(self) -> None:
        from fintech_quant.data.collection import select_star_market_universe

        records = [
            {"代码": "600000", "名称": "Not STAR", "成交额": 999_000_000},
            {"代码": "300001", "名称": "Not STAR Either", "成交额": 998_000_000},
        ]
        records.extend(
            {
                "代码": f"688{index:03d}",
                "名称": f"STAR {index}",
                "成交额": index * 1_000_000,
            }
            for index in range(1, 32)
        )

        universe = select_star_market_universe(records, limit=30)

        self.assertEqual(len(universe), 30)
        self.assertEqual(universe[0].symbol, "688031")
        self.assertEqual(universe[-1].symbol, "688002")
        self.assertTrue(all(item.symbol.startswith("688") for item in universe))

    def test_one_year_date_range_uses_akshare_format(self) -> None:
        from fintech_quant.data.collection import one_year_akshare_date_range

        date_range = one_year_akshare_date_range(today=date(2026, 6, 16))

        self.assertEqual(date_range.start, "20250616")
        self.assertEqual(date_range.end, "20260616")

    def test_accepts_sina_prefixed_star_market_symbols(self) -> None:
        from fintech_quant.data.collection import select_star_market_universe

        universe = select_star_market_universe(
            [
                {"代码": "sh688001", "名称": "STAR A", "成交额": 100},
                {"代码": "sz300001", "名称": "ChiNext", "成交额": 200},
            ],
            limit=30,
        )

        self.assertEqual([item.symbol for item in universe], ["sh688001"])

    def test_converts_akshare_date_to_iso_date(self) -> None:
        from fintech_quant.data.collection import akshare_date_to_iso, date_value_to_iso

        self.assertEqual(akshare_date_to_iso("20250616"), "2025-06-16")
        self.assertEqual(date_value_to_iso(date(2026, 6, 16)), "2026-06-16")

    def test_estimates_30_symbol_daily_collection_as_small_local_files(self) -> None:
        from fintech_quant.data.collection import estimate_daily_collection_size

        estimate = estimate_daily_collection_size(symbol_count=30, trading_days=250)

        self.assertEqual(estimate.rows, 7500)
        self.assertLess(estimate.csv_megabytes, 5.0)
        self.assertLess(estimate.runtime_megabytes, 20.0)


if __name__ == "__main__":
    unittest.main()
