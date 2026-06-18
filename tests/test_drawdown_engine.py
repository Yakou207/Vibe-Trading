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
        self.assertEqual(result.liquidation_date, date(2026, 1, 4))

    def test_rejects_empty_equity_curve(self) -> None:
        from fintech_quant.backtesting.drawdown import calculate_drawdown

        with self.assertRaises(ValueError):
            calculate_drawdown([])


if __name__ == "__main__":
    unittest.main()
