from __future__ import annotations

from datetime import date
import unittest

from fintech_quant.backtesting import run_scored_baseline_backtest
from fintech_quant.features import ComponentScore, StockScore
from fintech_quant.risk import RiskInput
from fintech_quant.trading import TradeAction


def make_score(symbol: str, total: float) -> StockScore:
    return StockScore(
        symbol=symbol,
        total=total,
        components={
            "fundamental": ComponentScore("fundamental", total, 35.0, ()),
            "technical": ComponentScore("technical", 0.0, 25.0, ()),
            "capital": ComponentScore("capital", 0.0, 25.0, ()),
            "sentiment": ComponentScore("sentiment", 0.0, 15.0, ()),
        },
        confidence=1.0,
        missing_fields=(),
    )


class ResearchBacktestRunnerTest(unittest.TestCase):
    def test_baseline_runner_buys_holds_and_sells_on_risk(self) -> None:
        bars = [
            {"symbol": "000001.SZ", "trade_date": "2026-01-01", "close": 10.0},
            {"symbol": "000001.SZ", "trade_date": "2026-01-02", "close": 12.0},
            {"symbol": "000001.SZ", "trade_date": "2026-01-03", "close": 9.0},
        ]
        scores = {
            date(2026, 1, 1): make_score("000001.SZ", 80.0),
            date(2026, 1, 2): make_score("000001.SZ", 80.0),
            date(2026, 1, 3): make_score("000001.SZ", 80.0),
        }
        risk_inputs = {
            date(2026, 1, 3): RiskInput(portfolio_drawdown=0.15),
        }

        result = run_scored_baseline_backtest(
            bars,
            scores,
            risk_inputs=risk_inputs,
            initial_cash=1000.0,
        )

        self.assertEqual([trade.action for trade in result.trades], [TradeAction.BUY, TradeAction.SELL])
        self.assertEqual(result.trades[0].shares, 100)
        self.assertEqual(result.trades[1].shares, 100)
        self.assertEqual([point.equity for point in result.equity_curve], [1000.0, 1200.0, 900.0])
        self.assertAlmostEqual(result.drawdown.max_drawdown, 0.25)
        self.assertEqual(result.summary["ending_equity"], 900.0)
        self.assertEqual(result.summary["total_return"], -0.10)
        self.assertEqual(result.summary["trade_count"], 2)
        self.assertEqual(result.risk_warnings[0].rule, "portfolio_drawdown")

    def test_baseline_runner_requires_score_for_each_bar_date(self) -> None:
        bars = [{"symbol": "000001.SZ", "trade_date": "2026-01-01", "close": 10.0}]

        with self.assertRaisesRegex(ValueError, "Missing score"):
            run_scored_baseline_backtest(bars, {}, initial_cash=1000.0)

    def test_baseline_runner_rejects_mixed_symbols(self) -> None:
        bars = [
            {"symbol": "000001.SZ", "trade_date": "2026-01-01", "close": 10.0},
            {"symbol": "600000.SH", "trade_date": "2026-01-02", "close": 12.0},
        ]
        scores = {
            date(2026, 1, 1): make_score("000001.SZ", 80.0),
            date(2026, 1, 2): make_score("600000.SH", 80.0),
        }

        with self.assertRaisesRegex(ValueError, "one symbol"):
            run_scored_baseline_backtest(bars, scores, initial_cash=1000.0)

    def test_baseline_runner_rejects_duplicate_bar_dates(self) -> None:
        bars = [
            {"symbol": "000001.SZ", "trade_date": "2026-01-01", "close": 10.0},
            {"symbol": "000001.SZ", "trade_date": "2026-01-01", "close": 12.0},
        ]
        scores = {
            date(2026, 1, 1): make_score("000001.SZ", 80.0),
        }

        with self.assertRaisesRegex(ValueError, "Duplicate bar date"):
            run_scored_baseline_backtest(bars, scores, initial_cash=1000.0)

    def test_baseline_runner_rejects_score_symbol_mismatch(self) -> None:
        bars = [
            {"symbol": "000001.SZ", "trade_date": "2026-01-01", "close": 10.0},
        ]
        scores = {
            date(2026, 1, 1): make_score("600000.SH", 80.0),
        }

        with self.assertRaisesRegex(ValueError, "Score symbol"):
            run_scored_baseline_backtest(bars, scores, initial_cash=1000.0)


if __name__ == "__main__":
    unittest.main()
