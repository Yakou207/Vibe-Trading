from __future__ import annotations

import unittest
from datetime import date


class TushareInformationFetcherTest(unittest.TestCase):
    def test_tushare_fundamental_fetcher_requires_token(self) -> None:
        from fintech_quant.data.errors import MissingProviderCredential
        from fintech_quant.information import TushareFundamentalFetcher

        fetcher = TushareFundamentalFetcher(token="")

        with self.assertRaises(MissingProviderCredential):
            fetcher.fetch("000001", None, date(2026, 1, 1), date(2026, 1, 31))

    def test_tushare_fundamental_fetcher_builds_selected_universe_stock_data(self) -> None:
        from fintech_quant.information import InformationCategory, TushareFundamentalFetcher

        def daily_basic_fetcher(**_: object) -> list[dict[str, object]]:
            return [{"trade_date": "20260115", "pe_ttm": "18.5", "pb": "1.4"}]

        def financial_indicator_fetcher(**_: object) -> list[dict[str, object]]:
            return [{"end_date": "20260115", "roe_dt": "12.5", "revenue_yoy": "8.2"}]

        fetcher = TushareFundamentalFetcher(
            token="token",
            daily_basic_fetcher=daily_basic_fetcher,
            financial_indicator_fetcher=financial_indicator_fetcher,
        )

        records = fetcher.fetch("000001", None, date(2026, 1, 1), date(2026, 1, 31))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source, "tushare_fundamental")
        self.assertEqual(records[0].category, InformationCategory.STOCK_DATA)
        self.assertEqual(records[0].risk_tags, ("selected_universe", "fundamental", "tushare"))
        self.assertEqual(records[0].published_at, date(2026, 1, 15))
        self.assertEqual(records[0].summary, "pe=18.5; pb=1.4; roe=0.125; growth=0.082")


if __name__ == "__main__":
    unittest.main()
