from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch


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

    def test_normalize_daily_bar_canonicalizes_trade_date_formats(self) -> None:
        from datetime import datetime

        from fintech_quant.data.base import normalize_daily_bar

        cases = [
            ("20260603", "2026-06-03"),
            ("2026-06-03", "2026-06-03"),
            (date(2026, 6, 3), "2026-06-03"),
            (datetime(2026, 6, 3, 9, 30), "2026-06-03"),
        ]

        for raw_trade_date, expected in cases:
            with self.subTest(raw_trade_date=raw_trade_date):
                row = {"trade_date": raw_trade_date}
                self.assertEqual(
                    normalize_daily_bar("000001", row, "akshare")["trade_date"],
                    expected,
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
                    "trade_date": "2026-06-03",
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

    def test_akshare_provider_wraps_missing_dependency(self) -> None:
        from fintech_quant.data.akshare_provider import AkShareProvider
        from fintech_quant.data.errors import MissingProviderDependency

        with patch(
            "fintech_quant.data.akshare_provider.importlib.import_module",
            side_effect=ImportError("No module named 'akshare'"),
        ):
            with self.assertRaisesRegex(MissingProviderDependency, "akshare"):
                AkShareProvider().history("000001", date(2026, 6, 1), date(2026, 6, 3))

    def test_tushare_provider_wraps_fetch_failures(self) -> None:
        from fintech_quant.data.errors import ProviderFetchError
        from fintech_quant.data.tushare_provider import TushareProvider

        def fetcher(**_: object) -> list[dict[str, object]]:
            raise RuntimeError("upstream timeout")

        provider = TushareProvider(token="token", fetcher=fetcher)

        with self.assertRaisesRegex(ProviderFetchError, "tushare"):
            provider.history("000001", date(2026, 6, 1), date(2026, 6, 3))

    def test_akshare_provider_wraps_normalization_failures(self) -> None:
        from fintech_quant.data.errors import ProviderFetchError
        from fintech_quant.data.akshare_provider import AkShareProvider

        def fetcher(**_: object) -> list[dict[str, object]]:
            return [{"日期": "bad-date"}]

        provider = AkShareProvider(fetcher=fetcher)

        with self.assertRaisesRegex(ProviderFetchError, "akshare"):
            provider.history("000001", date(2026, 6, 1), date(2026, 6, 3))

    def test_tushare_provider_wraps_normalization_failures(self) -> None:
        from fintech_quant.data.errors import ProviderFetchError
        from fintech_quant.data.tushare_provider import TushareProvider

        def fetcher(**_: object) -> list[dict[str, object]]:
            return [{"trade_date": "bad-date"}]

        provider = TushareProvider(token="token", fetcher=fetcher)

        with self.assertRaisesRegex(ProviderFetchError, "tushare"):
            provider.history("000001", date(2026, 6, 1), date(2026, 6, 3))


if __name__ == "__main__":
    unittest.main()
