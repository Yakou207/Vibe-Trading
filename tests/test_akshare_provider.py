from datetime import date
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

import pandas as pd


class AkShareProviderTest(unittest.TestCase):
    def test_history_normalizes_akshare_daily_bars(self) -> None:
        from fintech_quant.data.akshare_provider import AkShareProvider

        calls = []

        def fake_stock_zh_a_hist(**kwargs):
            calls.append(kwargs)
            return pd.DataFrame(
                [
                    {
                        "日期": "2024-01-02",
                        "开盘": 10.0,
                        "最高": 11.0,
                        "最低": 9.5,
                        "收盘": 10.5,
                        "成交量": 1000,
                        "成交额": 10500.0,
                        "换手率": 1.2,
                    }
                ]
            )

        fake_akshare = SimpleNamespace(stock_zh_a_hist=fake_stock_zh_a_hist)

        with patch.dict(sys.modules, {"akshare": fake_akshare}):
            rows = AkShareProvider(adjust="qfq").history(
                "sh688008", date(2024, 1, 1), date(2024, 1, 31)
            )

        self.assertEqual(calls[0]["symbol"], "688008")
        self.assertEqual(calls[0]["start_date"], "20240101")
        self.assertEqual(calls[0]["end_date"], "20240131")
        self.assertEqual(calls[0]["adjust"], "qfq")
        self.assertEqual(
            rows[0],
            {
                "symbol": "sh688008",
                "date": "2024-01-02",
                "open": 10.0,
                "high": 11.0,
                "low": 9.5,
                "close": 10.5,
                "volume": 1000.0,
                "amount": 10500.0,
                "turnover": 1.2,
            },
        )


if __name__ == "__main__":
    unittest.main()
