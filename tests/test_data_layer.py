from __future__ import annotations

import unittest
from datetime import date


class DataLayerTest(unittest.TestCase):
    def test_normalize_a_share_symbol_adds_exchange_suffix(self) -> None:
        from fintech_quant.data.symbols import normalize_a_share_symbol

        self.assertEqual(normalize_a_share_symbol("000001"), "000001.SZ")
        self.assertEqual(normalize_a_share_symbol("600000"), "600000.SH")
        self.assertEqual(normalize_a_share_symbol("688001"), "688001.SH")
        self.assertEqual(normalize_a_share_symbol("000001.sz"), "000001.SZ")

    def test_normalize_a_share_symbol_rejects_unknown_code(self) -> None:
        from fintech_quant.data.symbols import normalize_a_share_symbol

        with self.assertRaises(ValueError):
            normalize_a_share_symbol("123")

    def test_normalize_daily_bar_maps_common_chinese_columns(self) -> None:
        from fintech_quant.data.base import normalize_daily_bar

        row = {
            "日期": "2026-06-01",
            "开盘": "10.1",
            "最高": "10.8",
            "最低": "9.9",
            "收盘": "10.5",
            "成交量": "12345",
            "成交额": "67890.5",
        }

        self.assertEqual(
            normalize_daily_bar("000001", row, "akshare"),
            {
                "symbol": "000001.SZ",
                "trade_date": "2026-06-01",
                "open": 10.1,
                "high": 10.8,
                "low": 9.9,
                "close": 10.5,
                "volume": 12345.0,
                "amount": 67890.5,
                "source": "akshare",
            },
        )

    def test_provider_registry_auto_routes_a_share_to_akshare(self) -> None:
        from fintech_quant.data.base import MarketDataProvider
        from fintech_quant.data.registry import ProviderRegistry

        class FakeProvider(MarketDataProvider):
            name = "akshare"

            def history(self, symbol: str, start: date, end: date) -> list[dict[str, object]]:
                return [{"symbol": symbol, "trade_date": str(start), "source": self.name}]

        registry = ProviderRegistry()
        registry.register(FakeProvider())

        rows = registry.history("000001", date(2026, 1, 1), date(2026, 1, 2))

        self.assertEqual(rows, [{"symbol": "000001.SZ", "trade_date": "2026-01-01", "source": "akshare"}])

    def test_tushare_provider_requires_token_before_use(self) -> None:
        from fintech_quant.data.errors import MissingProviderCredential
        from fintech_quant.data.tushare_provider import TushareProvider

        provider = TushareProvider(token="")

        with self.assertRaises(MissingProviderCredential):
            provider.history("000001", date(2026, 1, 1), date(2026, 1, 2))

    def test_tushare_provider_normalizes_successful_daily_rows(self) -> None:
        from fintech_quant.data.tushare_provider import TushareProvider

        def fetcher(**_: object) -> list[dict[str, object]]:
            return [
                {
                    "trade_date": "20260603",
                    "open": "10.2",
                    "high": "10.6",
                    "low": "10.0",
                    "close": "10.4",
                    "vol": "54321",
                    "amount": "76543.2",
                }
            ]

        provider = TushareProvider(token="token", fetcher=fetcher)

        self.assertEqual(
            provider.history("000001", date(2026, 6, 1), date(2026, 6, 3)),
            [
                {
                    "symbol": "000001.SZ",
                    "trade_date": "20260603",
                    "open": 10.2,
                    "high": 10.6,
                    "low": 10.0,
                    "close": 10.4,
                    "volume": 54321.0,
                    "amount": 76543.2,
                    "source": "tushare",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
