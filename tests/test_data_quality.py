from __future__ import annotations

import unittest


class DataQualityTest(unittest.TestCase):
    def test_audits_daily_records_for_key_price_and_volume_rules(self) -> None:
        from fintech_quant.data.quality import audit_daily_records

        records = [
            {
                "代码": "sh688001",
                "名称": "华兴源创",
                "date": "2026-06-15",
                "open": 10,
                "high": 12,
                "low": 9,
                "close": 11,
                "volume": 100,
            },
            {
                "代码": "sh688001",
                "名称": "华兴源创",
                "date": "2026-06-15",
                "open": 10,
                "high": 12,
                "low": 9,
                "close": 11,
                "volume": 100,
            },
            {
                "代码": "sz002475",
                "名称": "立讯精密",
                "date": "2026-06-16",
                "open": 20,
                "high": 19,
                "low": 18,
                "close": 21,
                "volume": -1,
            },
        ]

        report = audit_daily_records(records)

        self.assertEqual(report.rows, 3)
        self.assertEqual(report.symbols, 2)
        self.assertEqual(report.duplicate_symbol_dates, 1)
        self.assertEqual(report.ohlc_violations, 1)
        self.assertEqual(report.negative_volume_rows, 1)
        self.assertFalse(report.passes_core_checks)


if __name__ == "__main__":
    unittest.main()
