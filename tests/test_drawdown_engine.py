from __future__ import annotations

import unittest
from datetime import date


class DrawdownEngineTest(unittest.TestCase):
    def test_calculates_rolling_peak_drawdown_and_liquidation_date(self) -> None:
        from fintech_quant.backtesting.drawdown import EquityPoint, calculate_drawdown

        result = calculate_drawdown(
            [
                EquityPoint(date(2026, 1, 1), 100.0),
                EquityPoint(date(2026, 1, 2), 110.0),
                EquityPoint(date(2026, 1, 3), 99.0),
                EquityPoint(date(2026, 1, 4), 90.0),
            ],
            liquidation_threshold=0.15,
        )

        self.assertEqual([point.rolling_peak for point in result.points], [100.0, 110.0, 110.0, 110.0])
        self.assertEqual([round(point.drawdown, 4) for point in result.points], [0.0, 0.0, 0.1, 0.1818])
        self.assertAlmostEqual(result.max_drawdown, 0.1818, places=4)
        self.assertEqual(result.max_drawdown_start, date(2026, 1, 2))
        self.assertEqual(result.max_drawdown_end, date(2026, 1, 4))
        self.assertIsNone(result.recovery_date)
        self.assertEqual(result.liquidation_date, date(2026, 1, 4))

    def test_tracks_recovery_date_after_max_drawdown(self) -> None:
        from fintech_quant.backtesting.drawdown import EquityPoint, calculate_drawdown

        result = calculate_drawdown(
            [
                EquityPoint(date(2026, 1, 1), 100.0),
                EquityPoint(date(2026, 1, 2), 120.0),
                EquityPoint(date(2026, 1, 3), 90.0),
                EquityPoint(date(2026, 1, 4), 121.0),
            ],
            liquidation_threshold=0.15,
        )

        self.assertAlmostEqual(result.max_drawdown, 0.25)
        self.assertEqual(result.max_drawdown_start, date(2026, 1, 2))
        self.assertEqual(result.max_drawdown_end, date(2026, 1, 3))
        self.assertEqual(result.recovery_date, date(2026, 1, 4))

    def test_reports_drawdown_episodes_with_duration_and_recovery_days(self) -> None:
        from fintech_quant.backtesting.drawdown import EquityPoint, calculate_drawdown

        result = calculate_drawdown(
            [
                EquityPoint(date(2026, 1, 1), 100.0),
                EquityPoint(date(2026, 1, 2), 90.0),
                EquityPoint(date(2026, 1, 3), 101.0),
                EquityPoint(date(2026, 1, 4), 95.0),
                EquityPoint(date(2026, 1, 5), 102.0),
            ]
        )

        self.assertEqual(len(result.episodes), 2)
        self.assertEqual(result.episodes[0].start_date, date(2026, 1, 1))
        self.assertEqual(result.episodes[0].trough_date, date(2026, 1, 2))
        self.assertEqual(result.episodes[0].recovery_date, date(2026, 1, 3))
        self.assertAlmostEqual(result.episodes[0].max_drawdown, 0.1)
        self.assertEqual(result.episodes[0].duration_days, 2)
        self.assertEqual(result.episodes[0].recovery_days, 2)
        self.assertEqual(result.episodes[1].start_date, date(2026, 1, 3))
        self.assertEqual(result.episodes[1].trough_date, date(2026, 1, 4))
        self.assertEqual(result.episodes[1].recovery_date, date(2026, 1, 5))

    def test_rejects_empty_equity_curve(self) -> None:
        from fintech_quant.backtesting.drawdown import calculate_drawdown

        with self.assertRaises(ValueError):
            calculate_drawdown([])


if __name__ == "__main__":
    unittest.main()
