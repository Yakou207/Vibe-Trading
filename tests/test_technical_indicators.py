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
        self.assertIsNone(enriched[2]["rsi3"])
        self.assertIsNone(enriched[2]["volatility3"])
        self.assertAlmostEqual(enriched[3]["rsi3"], 69.61326)
        self.assertAlmostEqual(enriched[3]["volatility3"], 0.084363)
        self.assertAlmostEqual(enriched[-1]["rsi3"], 76.595745)
        self.assertAlmostEqual(enriched[-1]["macd_line"], 0.428596)
        self.assertAlmostEqual(enriched[-1]["macd_signal"], 0.162128)
        self.assertAlmostEqual(enriched[-1]["macd_hist"], 0.266467)
        self.assertTrue(enriched[-1]["macd_positive"])
        self.assertAlmostEqual(enriched[-1]["volatility3"], 0.110015)

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

    def test_enrich_daily_bars_adds_relative_strength_rank_across_universe(self) -> None:
        from fintech_quant.features import enrich_daily_bars

        rows = [
            _bar("000001.SZ", "2026-01-01", 10.0),
            _bar("000002.SZ", "2026-01-01", 10.0),
            _bar("600000.SH", "2026-01-01", 10.0),
            _bar("000001.SZ", "2026-01-02", 11.0),
            _bar("000002.SZ", "2026-01-02", 10.5),
            _bar("600000.SH", "2026-01-02", 9.0),
            _bar("000001.SZ", "2026-01-03", 12.0),
            _bar("000002.SZ", "2026-01-03", 11.0),
            _bar("600000.SH", "2026-01-03", 9.5),
        ]

        enriched = enrich_daily_bars(rows, relative_strength_window=2)
        by_symbol_date = {(row["symbol"], row["trade_date"]): row for row in enriched}

        self.assertIsNone(by_symbol_date[("000001.SZ", "2026-01-02")]["return_2d"])
        self.assertAlmostEqual(by_symbol_date[("000001.SZ", "2026-01-03")]["return_2d"], 0.2)
        self.assertAlmostEqual(by_symbol_date[("000001.SZ", "2026-01-03")]["rs_rank_2d"], 1.0)
        self.assertAlmostEqual(by_symbol_date[("000002.SZ", "2026-01-03")]["rs_rank_2d"], 0.5)
        self.assertAlmostEqual(by_symbol_date[("600000.SH", "2026-01-03")]["rs_rank_2d"], 0.0)

    def test_enrich_daily_bars_treats_flat_rsi_window_as_neutral(self) -> None:
        from fintech_quant.features import enrich_daily_bars

        rows = [
            _bar("000001.SZ", "2026-01-01", 10.0),
            _bar("000001.SZ", "2026-01-02", 10.0),
            _bar("000001.SZ", "2026-01-03", 10.0),
            _bar("000001.SZ", "2026-01-04", 10.0),
        ]

        enriched = enrich_daily_bars(rows, rsi_period=3)

        self.assertAlmostEqual(enriched[-1]["rsi3"], 50.0)

    def test_enrich_daily_bars_computes_limit_up_streak_per_symbol(self) -> None:
        from fintech_quant.features import enrich_daily_bars

        rows = [
            _bar("000001.SZ", "2026-01-01", 10.0, limit_up=True),
            _bar("000001.SZ", "2026-01-02", 11.0, limit_up=True),
            _bar("000001.SZ", "2026-01-03", 10.5, limit_up=False),
            _bar("000001.SZ", "2026-01-04", 11.55, limit_up=True),
            _bar("600000.SH", "2026-01-01", 20.0, limit_up=True),
        ]

        enriched = enrich_daily_bars(rows)
        by_symbol_date = {(row["symbol"], row["trade_date"]): row for row in enriched}

        self.assertEqual(by_symbol_date[("000001.SZ", "2026-01-01")]["limit_up_streak"], 1)
        self.assertEqual(by_symbol_date[("000001.SZ", "2026-01-02")]["limit_up_streak"], 2)
        self.assertEqual(by_symbol_date[("000001.SZ", "2026-01-03")]["limit_up_streak"], 0)
        self.assertEqual(by_symbol_date[("000001.SZ", "2026-01-04")]["limit_up_streak"], 1)
        self.assertEqual(by_symbol_date[("600000.SH", "2026-01-01")]["limit_up_streak"], 1)

    def test_enrich_daily_bars_keeps_limit_up_streak_missing_without_source_flag(self) -> None:
        from fintech_quant.features import enrich_daily_bars

        rows = [
            _bar("000001.SZ", "2026-01-01", 10.0),
            _bar("000001.SZ", "2026-01-02", 11.0),
        ]

        enriched = enrich_daily_bars(rows)

        self.assertIsNone(enriched[0]["limit_up_streak"])
        self.assertIsNone(enriched[1]["limit_up_streak"])

    def test_enrich_daily_bars_resets_limit_up_streak_after_missing_source_flag(self) -> None:
        from fintech_quant.features import enrich_daily_bars

        rows = [
            _bar("000001.SZ", "2026-01-01", 10.0, limit_up=True),
            _bar("000001.SZ", "2026-01-02", 11.0),
            _bar("000001.SZ", "2026-01-03", 12.1, limit_up=True),
        ]

        enriched = enrich_daily_bars(rows)

        self.assertEqual(enriched[0]["limit_up_streak"], 1)
        self.assertIsNone(enriched[1]["limit_up_streak"])
        self.assertEqual(enriched[2]["limit_up_streak"], 1)


def _bar(symbol: str, trade_date: str, close: float, *, limit_up: bool | None = None) -> dict[str, object]:
    row: dict[str, object] = {
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
    if limit_up is not None:
        row["limit_up"] = limit_up
    return row

if __name__ == "__main__":
    unittest.main()
