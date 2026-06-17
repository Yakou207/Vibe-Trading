from __future__ import annotations

import unittest

import pandas as pd


class BacktestingEngineTest(unittest.TestCase):
    def test_equal_weight_buy_and_hold_backtest_creates_trades_and_equity_curve(self) -> None:
        from fintech_quant.backtesting.engine import BacktestConfig, run_daily_backtest
        from fintech_quant.strategies.buy_and_hold import EqualWeightBuyAndHoldStrategy

        features = pd.DataFrame(
            {
                "代码": ["sh688001", "sh688002", "sh688001", "sh688002"],
                "date": ["2024-01-02", "2024-01-02", "2024-01-03", "2024-01-03"],
                "close": [10.0, 20.0, 11.0, 19.0],
            }
        )

        result = run_daily_backtest(
            features=features,
            strategy=EqualWeightBuyAndHoldStrategy(target_weight=0.45),
            config=BacktestConfig(
                initial_cash=10_000.0,
                max_position_weight=0.5,
                commission_rate=0.0,
                stamp_tax_rate=0.0,
                slippage_rate=0.0,
            ),
        )

        self.assertEqual(result.metrics.trade_count, 2)
        self.assertEqual(result.metrics.buy_count, 2)
        self.assertEqual(result.metrics.sell_count, 0)
        self.assertEqual(len(result.equity_curve), 2)
        self.assertEqual(result.metrics.start_date, "2024-01-02")
        self.assertEqual(result.metrics.end_date, "2024-01-03")
        self.assertAlmostEqual(result.metrics.final_equity, 10_200.0)
        self.assertAlmostEqual(result.metrics.total_return, 0.02)
        self.assertIsInstance(result.metrics.sharpe_ratio, float)

    def test_backtest_rejects_missing_required_columns(self) -> None:
        from fintech_quant.backtesting.engine import BacktestConfig, run_daily_backtest
        from fintech_quant.strategies.buy_and_hold import EqualWeightBuyAndHoldStrategy

        with self.assertRaisesRegex(ValueError, "close"):
            run_daily_backtest(
                features=pd.DataFrame({"代码": ["sh688001"], "date": ["2024-01-02"]}),
                strategy=EqualWeightBuyAndHoldStrategy(),
                config=BacktestConfig(),
            )


if __name__ == "__main__":
    unittest.main()
