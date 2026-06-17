from __future__ import annotations

import unittest

import pandas as pd

from fintech_quant.trading import TradeAction, TradeDecision


class BuySignalStrategy:
    name = "buy_signal"

    def decide(self, state: dict[str, object]) -> TradeDecision:
        if int(state.get("position_quantity", 0)) > 0:
            return TradeDecision(TradeAction.HOLD, 0.0, "Already holding.")
        return TradeDecision(TradeAction.BUY, 0.5, "Buy signal.")


class BuyThenSellSignalStrategy:
    name = "buy_then_sell_signal"

    def decide(self, state: dict[str, object]) -> TradeDecision:
        date = str(state["date"])
        if date == "2024-01-02":
            return TradeDecision(TradeAction.BUY, 0.5, "Buy signal.")
        if date == "2024-01-03":
            return TradeDecision(TradeAction.SELL, 1.0, "Sell signal.")
        return TradeDecision(TradeAction.HOLD, 0.0, "No signal.")


class BacktestingEngineTest(unittest.TestCase):
    def test_equal_weight_buy_and_hold_backtest_creates_trades_and_equity_curve(self) -> None:
        from fintech_quant.backtesting.engine import BacktestConfig, run_daily_backtest
        from fintech_quant.strategies.buy_and_hold import EqualWeightBuyAndHoldStrategy

        features = pd.DataFrame(
            {
                "代码": ["sh688001", "sh688002", "sh688001", "sh688002"],
                "date": ["2024-01-02", "2024-01-02", "2024-01-03", "2024-01-03"],
                "open": [10.0, 20.0, 10.5, 19.5],
                "close": [10.0, 20.0, 11.0, 19.0],
                "volume": [1000, 1000, 1000, 1000],
                "return_1d": [0.0, 0.0, 0.1, -0.05],
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
        self.assertEqual(result.trades[0].date, "2024-01-03")
        self.assertEqual(result.trades[0].price, 10.5)
        self.assertAlmostEqual(result.metrics.final_equity, 10_100.0)
        self.assertAlmostEqual(result.metrics.total_return, 0.01)
        self.assertIsInstance(result.metrics.sharpe_ratio, float)

    def test_backtest_executes_signal_on_next_trading_day_open(self) -> None:
        from fintech_quant.backtesting.engine import BacktestConfig, run_daily_backtest

        features = pd.DataFrame(
            {
                "代码": ["sh688001", "sh688001"],
                "date": ["2024-01-02", "2024-01-03"],
                "open": [10.0, 12.0],
                "close": [11.0, 13.0],
                "volume": [1000, 1000],
                "return_1d": [0.0, 0.1818],
            }
        )

        result = run_daily_backtest(
            features,
            BuySignalStrategy(),
            BacktestConfig(
                initial_cash=10_000.0,
                max_position_weight=0.7,
                commission_rate=0.0,
                stamp_tax_rate=0.0,
                slippage_rate=0.0,
            ),
        )

        self.assertEqual(result.metrics.trade_count, 1)
        self.assertEqual(result.trades[0].date, "2024-01-03")
        self.assertEqual(result.trades[0].price, 12.0)
        self.assertEqual(result.trades[0].quantity, 400)

    def test_backtest_blocks_buy_on_limit_up_and_sell_on_limit_down(self) -> None:
        from fintech_quant.backtesting.engine import BacktestConfig, run_daily_backtest

        limit_up_features = pd.DataFrame(
            {
                "代码": ["sh688001", "sh688001"],
                "date": ["2024-01-02", "2024-01-03"],
                "open": [10.0, 12.0],
                "close": [10.0, 12.0],
                "volume": [1000, 1000],
                "return_1d": [0.0, 0.20],
            }
        )

        blocked_buy = run_daily_backtest(
            limit_up_features,
            BuySignalStrategy(),
            BacktestConfig(initial_cash=10_000.0, max_position_weight=0.7),
        )

        self.assertEqual(blocked_buy.metrics.trade_count, 0)

        limit_down_features = pd.DataFrame(
            {
                "代码": ["sh688001", "sh688001", "sh688001"],
                "date": ["2024-01-02", "2024-01-03", "2024-01-04"],
                "open": [10.0, 10.0, 8.0],
                "close": [10.0, 10.0, 8.0],
                "volume": [1000, 1000, 1000],
                "return_1d": [0.0, 0.0, -0.20],
            }
        )

        blocked_sell = run_daily_backtest(
            limit_down_features,
            BuyThenSellSignalStrategy(),
            BacktestConfig(
                initial_cash=10_000.0,
                max_position_weight=0.7,
                commission_rate=0.0,
                stamp_tax_rate=0.0,
                slippage_rate=0.0,
            ),
        )

        self.assertEqual(blocked_sell.metrics.buy_count, 1)
        self.assertEqual(blocked_sell.metrics.sell_count, 0)

    def test_backtest_blocks_trades_on_zero_volume_suspension_day(self) -> None:
        from fintech_quant.backtesting.engine import BacktestConfig, run_daily_backtest

        features = pd.DataFrame(
            {
                "代码": ["sh688001", "sh688001"],
                "date": ["2024-01-02", "2024-01-03"],
                "open": [10.0, 10.0],
                "close": [10.0, 10.0],
                "volume": [1000, 0],
                "return_1d": [0.0, 0.0],
            }
        )

        result = run_daily_backtest(
            features,
            BuySignalStrategy(),
            BacktestConfig(initial_cash=10_000.0, max_position_weight=0.7),
        )

        self.assertEqual(result.metrics.trade_count, 0)

    def test_backtest_uses_execution_price_for_price_limit_checks(self) -> None:
        from fintech_quant.backtesting.engine import BacktestConfig, run_daily_backtest

        features = pd.DataFrame(
            {
                "代码": ["sh688001", "sh688001"],
                "date": ["2024-01-02", "2024-01-03"],
                "open": [10.0, 12.0],
                "close": [10.0, 10.5],
                "volume": [1000, 1000],
                "return_1d": [0.0, 0.05],
            }
        )

        result = run_daily_backtest(
            features,
            BuySignalStrategy(),
            BacktestConfig(initial_cash=10_000.0, max_position_weight=0.7),
        )

        self.assertEqual(result.metrics.trade_count, 0)

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
