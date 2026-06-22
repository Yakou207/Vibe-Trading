from __future__ import annotations

import unittest


class TechnicalIndicatorsTest(unittest.TestCase):
    def test_enrich_daily_bars_adds_returns_moving_averages_rsi_macd_and_volatility(self) -> None:
        from fintech_quant.features import enrich_daily_bars

        rows = [
            _bar("000001.SZ", "2026-01-01", 10.0),
            _bar("000001.SZ", "2026-01-02", 11.0),
            _bar("000001.SZ", "2026-01-03", 12.0),
            _bar("000001.SZ", "2026-01-04", 11.0),
            _bar("000001.SZ", "2026-01-05", 13.0),
        ]

        enriched = enrich_daily_bars(rows, ma_windows=(2, 3), rsi_period=3, volatility_window=3)

        self.assertIsNone(enriched[0]["return_1d"])
        self.assertAlmostEqual(enriched[1]["return_1d"], 0.1)
        self.assertAlmostEqual(enriched[2]["ma2"], 11.5)
        self.assertAlmostEqual(enriched[2]["ma3"], 11.0)
        self.assertTrue(enriched[2]["close_above_ma2"])
        self.assertTrue(enriched[2]["close_above_ma3"])
        self.assertIsNotNone(enriched[-1]["rsi3"])
        self.assertIsNotNone(enriched[-1]["macd_line"])
        self.assertIsNotNone(enriched[-1]["macd_signal"])
        self.assertIsNotNone(enriched[-1]["macd_hist"])
        self.assertIsInstance(enriched[-1]["macd_positive"], bool)
        self.assertIsNotNone(enriched[-1]["volatility3"])

    def test_enrich_daily_bars_computes_each_symbol_independently(self) -> None:
        from fintech_quant.features import enrich_daily_bars

        rows = [
            _bar("000001.SZ", "2026-01-01", 10.0),
            _bar("600000.SH", "2026-01-01", 20.0),
            _bar("000001.SZ", "2026-01-02", 12.0),
            _bar("600000.SH", "2026-01-02", 18.0),
        ]

        enriched = enrich_daily_bars(rows, ma_windows=(2,), rsi_period=2, volatility_window=2)
        by_symbol_date = {(row["symbol"], row["trade_date"]): row for row in enriched}

        self.assertAlmostEqual(by_symbol_date[("000001.SZ", "2026-01-02")]["return_1d"], 0.2)
        self.assertAlmostEqual(by_symbol_date[("600000.SH", "2026-01-02")]["return_1d"], -0.1)
        self.assertAlmostEqual(by_symbol_date[("000001.SZ", "2026-01-02")]["ma2"], 11.0)
        self.assertAlmostEqual(by_symbol_date[("600000.SH", "2026-01-02")]["ma2"], 19.0)


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
