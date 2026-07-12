from __future__ import annotations

import unittest
from datetime import date

from fintech_quant.features import ComponentScore, StockScore
from fintech_quant.risk import RiskInput
from fintech_quant.trading import TradeAction


class PortfolioResearchRunnerTest(unittest.TestCase):
    def test_portfolio_runner_separates_adjusted_signal_and_unadjusted_execution_prices(
        self,
    ) -> None:
        from fintech_quant.backtesting import run_portfolio_scored_baseline_backtest
        from fintech_quant.backtesting.costs import AShareCostModel

        signal_bars = [
            _bar("000001.SZ", "2026-01-01", 5.0),
            _bar("000001.SZ", "2026-01-02", 6.0),
        ]
        execution_bars = [
            _bar("000001.SZ", "2026-01-01", 10.0, source="unadjusted"),
            _bar("000001.SZ", "2026-01-02", 12.0, source="unadjusted"),
        ]
        scores = {
            (date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0),
            (date(2026, 1, 2), "000001.SZ"): _score("000001.SZ", 80.0),
        }

        result = run_portfolio_scored_baseline_backtest(
            signal_bars,
            scores,
            execution_bars=execution_bars,
            initial_cash=10000.0,
            max_position_weight=1.0,
            cost_model=AShareCostModel(
                commission_rate=0.0,
                minimum_commission=0.0,
                include_stamp_duty=False,
            ),
        )

        self.assertEqual(result.trades[0].price, 10.0)
        self.assertEqual(result.trades[0].shares, 1000)
        self.assertEqual(result.equity_curve[-1].equity, 12000.0)
        self.assertEqual(result.summary["execution_price_mode"], "unadjusted_external")

    def test_portfolio_runner_fails_closed_when_execution_price_is_missing(self) -> None:
        from fintech_quant.backtesting import run_portfolio_scored_baseline_backtest

        signal_bars = [
            _bar("000001.SZ", "2026-01-01", 5.0),
            _bar("000001.SZ", "2026-01-02", 6.0),
        ]
        execution_bars = [_bar("000001.SZ", "2026-01-01", 10.0)]

        with self.assertRaisesRegex(
            ValueError,
            "execution bars missing 000001.SZ on 2026-01-02",
        ):
            run_portfolio_scored_baseline_backtest(
                signal_bars,
                {},
                execution_bars=execution_bars,
            )

    def test_portfolio_runner_applies_cash_dividend_on_ex_date(self) -> None:
        from fintech_quant.backtesting import (
            CorporateAction,
            run_portfolio_scored_baseline_backtest,
        )
        from fintech_quant.backtesting.costs import AShareCostModel

        bars = [
            _bar("000001.SZ", "2026-01-01", 10.0),
            _bar("000001.SZ", "2026-01-02", 9.5),
        ]
        scores = {
            (date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0),
            (date(2026, 1, 2), "000001.SZ"): _score("000001.SZ", 80.0),
        }

        result = run_portfolio_scored_baseline_backtest(
            bars,
            scores,
            corporate_actions=(
                CorporateAction(
                    symbol="000001.SZ",
                    ex_date=date(2026, 1, 2),
                    cash_dividend_per_share=0.5,
                    source="fixture",
                ),
            ),
            initial_cash=10000.0,
            max_position_weight=1.0,
            cost_model=AShareCostModel(
                commission_rate=0.0,
                minimum_commission=0.0,
                include_stamp_duty=False,
            ),
        )

        self.assertEqual(result.equity_curve[-1].equity, 10000.0)
        self.assertEqual(result.corporate_actions[0].cash_delta, 500.0)
        self.assertEqual(result.corporate_actions[0].shares_before, 1000)
        self.assertEqual(result.corporate_actions[0].shares_after, 1000)

    def test_portfolio_runner_withholds_dividend_tax_when_short_term_lot_is_sold(self) -> None:
        from fintech_quant.backtesting import (
            CorporateAction,
            IndividualAShareDividendTaxPolicy,
            run_portfolio_scored_baseline_backtest,
        )
        from fintech_quant.backtesting.costs import AShareCostModel
        from fintech_quant.trading import TradeDecision

        class ThresholdExitStrategy:
            def decide(self, state: dict[str, object]) -> TradeDecision:
                score = state["score"]
                action = TradeAction.BUY if score.total >= 70 else TradeAction.SELL
                return TradeDecision(action=action, confidence=1.0, reason="fixture threshold")

        bars = [
            _bar("000001.SZ", "2026-01-01", 10.0),
            _bar("000001.SZ", "2026-01-10", 10.0),
            _bar("000001.SZ", "2026-01-20", 10.0),
        ]
        scores = {
            (date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0),
            (date(2026, 1, 10), "000001.SZ"): _score("000001.SZ", 80.0),
            (date(2026, 1, 20), "000001.SZ"): _score("000001.SZ", 10.0),
        }
        result = run_portfolio_scored_baseline_backtest(
            bars,
            scores,
            corporate_actions=(
                CorporateAction(
                    symbol="000001.SZ",
                    ex_date=date(2026, 1, 10),
                    cash_dividend_per_share=1.0,
                    source="fixture",
                ),
            ),
            dividend_tax_policy=IndividualAShareDividendTaxPolicy(),
            strategy=ThresholdExitStrategy(),
            initial_cash=10000.0,
            max_position_weight=1.0,
            cost_model=AShareCostModel(
                commission_rate=0.0,
                minimum_commission=0.0,
                include_stamp_duty=False,
            ),
        )

        self.assertEqual(result.trades[-1].dividend_tax, 200.0)
        self.assertEqual(result.summary["dividend_tax_cost"], 200.0)
        self.assertEqual(result.equity_curve[-1].equity, 10800.0)

    def test_portfolio_runner_applies_bonus_share_multiplier_on_ex_date(self) -> None:
        from fintech_quant.backtesting import (
            CorporateAction,
            run_portfolio_scored_baseline_backtest,
        )
        from fintech_quant.backtesting.costs import AShareCostModel

        bars = [
            _bar("000001.SZ", "2026-01-01", 10.0),
            _bar("000001.SZ", "2026-01-02", 5.0),
        ]
        scores = {
            (date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0),
            (date(2026, 1, 2), "000001.SZ"): _score("000001.SZ", 80.0),
        }

        result = run_portfolio_scored_baseline_backtest(
            bars,
            scores,
            corporate_actions=(
                CorporateAction(
                    symbol="000001.SZ",
                    ex_date=date(2026, 1, 2),
                    share_multiplier=2.0,
                    source="fixture",
                ),
            ),
            initial_cash=10000.0,
            max_position_weight=1.0,
            cost_model=AShareCostModel(
                commission_rate=0.0,
                minimum_commission=0.0,
                include_stamp_duty=False,
            ),
        )

        self.assertEqual(result.equity_curve[-1].equity, 10000.0)
        self.assertEqual(result.corporate_actions[0].shares_after, 2000)

    def test_portfolio_runner_stages_reentry_from_shadow_nav_recovery(self) -> None:
        from fintech_quant.backtesting import (
            DrawdownControlPolicy,
            run_portfolio_scored_baseline_backtest,
        )
        from fintech_quant.backtesting.costs import AShareCostModel
        from fintech_quant.risk import RiskLimits

        prices = (10.0, 9.2, 8.0, 9.2, 9.4, 9.5)
        bars = [
            _bar("000001.SZ", f"2026-01-0{index}", price)
            for index, price in enumerate(prices, start=1)
        ]
        scores = {
            (date.fromisoformat(f"2026-01-0{index}"), "000001.SZ"): _score("000001.SZ", 80.0)
            for index in range(1, 7)
        }

        result = run_portfolio_scored_baseline_backtest(
            bars,
            scores,
            initial_cash=10000.0,
            max_position_weight=1.0,
            drawdown_policy=DrawdownControlPolicy(),
            risk_limits=RiskLimits(
                max_position_weight=1.0,
                max_portfolio_drawdown=1.0,
                max_single_position_drawdown=1.0,
            ),
            cost_model=AShareCostModel(
                commission_rate=0.0,
                minimum_commission=0.0,
                include_stamp_duty=False,
            ),
        )

        self.assertEqual(
            [trade.action for trade in result.trades],
            [
                TradeAction.BUY,
                TradeAction.SELL,
                TradeAction.SELL,
                TradeAction.BUY,
                TradeAction.BUY,
            ],
        )
        self.assertEqual([trade.shares for trade in result.trades], [1000, 500, 500, 400, 500])
        self.assertEqual(
            [row["to_regime"] for row in result.summary["drawdown_transitions"]],
            ["reduced", "liquidated", "reduced", "normal"],
        )

    def test_drawdown_liquidation_retries_after_limit_down_blocks_exit(self) -> None:
        from fintech_quant.backtesting import (
            DrawdownControlPolicy,
            run_portfolio_scored_baseline_backtest,
        )
        from fintech_quant.backtesting.costs import AShareCostModel
        from fintech_quant.risk import RiskLimits

        bars = [
            _bar("000001.SZ", "2026-01-01", 10.0),
            _bar("000001.SZ", "2026-01-02", 8.9),
            _bar("000001.SZ", "2026-01-03", 8.0, limit_down=True),
            _bar("000001.SZ", "2026-01-04", 8.0),
        ]
        scores = {
            (date.fromisoformat(f"2026-01-0{index}"), "000001.SZ"): _score("000001.SZ", 80.0)
            for index in range(1, 5)
        }

        result = run_portfolio_scored_baseline_backtest(
            bars,
            scores,
            initial_cash=10000.0,
            max_position_weight=1.0,
            drawdown_policy=DrawdownControlPolicy(),
            risk_limits=RiskLimits(
                max_position_weight=1.0,
                max_portfolio_drawdown=1.0,
                max_single_position_drawdown=1.0,
            ),
            cost_model=AShareCostModel(
                commission_rate=0.0,
                minimum_commission=0.0,
                include_stamp_duty=False,
            ),
        )

        self.assertEqual(
            [trade.trade_date for trade in result.trades],
            [
                date(2026, 1, 1),
                date(2026, 1, 4),
            ],
        )
        self.assertEqual(result.trades[-1].action, TradeAction.SELL)

    def test_portfolio_runner_executes_signal_on_next_session(self) -> None:
        from fintech_quant.backtesting import run_portfolio_scored_baseline_backtest
        from fintech_quant.backtesting.costs import AShareCostModel

        bars = [
            _bar("000001.SZ", "2026-01-02", 10.0),
            _bar("000001.SZ", "2026-01-05", 11.0),
        ]
        scores = {(date(2026, 1, 2), "000001.SZ"): _score("000001.SZ", 80.0)}

        result = run_portfolio_scored_baseline_backtest(
            bars,
            scores,
            initial_cash=100000.0,
            execution_delay_sessions=1,
            cost_model=AShareCostModel(
                commission_rate=0.0,
                minimum_commission=0.0,
                include_stamp_duty=False,
            ),
        )

        buy = result.trades[0]
        self.assertEqual(buy.signal_date, date(2026, 1, 2))
        self.assertEqual(buy.trade_date, date(2026, 1, 5))
        self.assertEqual(buy.price, 11.0)

    def test_portfolio_runner_executes_delayed_sell_at_next_session_open(self) -> None:
        from fintech_quant.backtesting import run_portfolio_scored_baseline_backtest
        from fintech_quant.backtesting.costs import AShareCostModel
        from fintech_quant.trading import TradeDecision

        class ThresholdExitStrategy:
            def decide(self, state: dict[str, object]) -> TradeDecision:
                score = state["score"]
                action = TradeAction.BUY if score.total >= 70 else TradeAction.SELL
                return TradeDecision(action=action, confidence=1.0, reason="fixture threshold")

        bars = [
            _bar("000001.SZ", "2026-01-02", 10.0),
            _bar("000001.SZ", "2026-01-05", 12.0, open=11.0),
            _bar("000001.SZ", "2026-01-06", 14.0, open=13.0),
        ]
        scores = {
            (date(2026, 1, 2), "000001.SZ"): _score("000001.SZ", 80.0),
            (date(2026, 1, 5), "000001.SZ"): _score("000001.SZ", 10.0),
        }

        result = run_portfolio_scored_baseline_backtest(
            bars,
            scores,
            initial_cash=100000.0,
            execution_delay_sessions=1,
            strategy=ThresholdExitStrategy(),
            cost_model=AShareCostModel(
                commission_rate=0.0,
                minimum_commission=0.0,
                include_stamp_duty=False,
            ),
        )

        self.assertEqual([trade.price for trade in result.trades], [11.0, 13.0])
        self.assertEqual(result.trades[1].signal_date, date(2026, 1, 5))
        self.assertEqual(result.trades[1].trade_date, date(2026, 1, 6))

    def test_portfolio_runner_buys_100_share_lots_with_position_cap(self) -> None:
        from fintech_quant.backtesting import run_portfolio_scored_baseline_backtest

        bars = [_bar("000001.SZ", "2026-01-01", 10.0)]
        scores = {(date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0)}

        result = run_portfolio_scored_baseline_backtest(bars, scores, initial_cash=100000.0)

        buy = result.trades[0]
        self.assertEqual(buy.action, TradeAction.BUY)
        self.assertEqual(buy.shares % 100, 0)
        self.assertEqual(buy.shares, 800)
        self.assertLessEqual(buy.notional, 8000.0)
        self.assertEqual(result.summary["trade_count"], 1)

    def test_portfolio_runner_scales_new_position_by_decision_confidence(self) -> None:
        from fintech_quant.backtesting import run_portfolio_scored_baseline_backtest
        from fintech_quant.strategies.scored_baseline import (
            ScoredBaselineStrategy,
            ScoredRlOverlayStrategy,
        )

        bars = [_bar("000001.SZ", "2026-01-01", 10.0)]
        scores = {(date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0)}
        strategy = ScoredRlOverlayStrategy(
            base_strategy=ScoredBaselineStrategy(),
            buy_weight_multiplier=0.5,
        )

        result = run_portfolio_scored_baseline_backtest(
            bars,
            scores,
            initial_cash=100000.0,
            max_position_weight=0.08,
            strategy=strategy,
            strategy_state_overlays={(date(2026, 1, 1), "000001.SZ"): {"rl_action": "buy"}},
        )

        self.assertEqual(result.trades[0].action, TradeAction.BUY)
        self.assertEqual(result.trades[0].shares, 400)
        self.assertEqual(result.trades[0].notional, 4000.0)

    def test_portfolio_runner_does_not_sell_same_day_as_buy(self) -> None:
        from fintech_quant.backtesting import run_portfolio_scored_baseline_backtest

        bars = [_bar("000001.SZ", "2026-01-01", 10.0)]
        scores = {(date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0)}
        risk_inputs = {(date(2026, 1, 1), "000001.SZ"): RiskInput(single_position_drawdown=0.2)}

        result = run_portfolio_scored_baseline_backtest(
            bars, scores, risk_inputs=risk_inputs, initial_cash=100000.0
        )

        self.assertNotIn(
            (date(2026, 1, 1), TradeAction.SELL),
            [(trade.trade_date, trade.action) for trade in result.trades],
        )

    def test_portfolio_runner_does_not_buy_suspended_stock(self) -> None:
        from fintech_quant.backtesting import run_portfolio_scored_baseline_backtest

        bars = [_bar("000001.SZ", "2026-01-01", 10.0, is_suspended=True)]
        scores = {(date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0)}

        result = run_portfolio_scored_baseline_backtest(bars, scores, initial_cash=100000.0)

        self.assertEqual(result.trades, [])

    def test_portfolio_runner_does_not_buy_limit_up_stock(self) -> None:
        from fintech_quant.backtesting import run_portfolio_scored_baseline_backtest

        bars = [_bar("000001.SZ", "2026-01-01", 10.0, limit_up=True)]
        scores = {(date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0)}

        result = run_portfolio_scored_baseline_backtest(bars, scores, initial_cash=100000.0)

        self.assertEqual(result.trades, [])

    def test_portfolio_runner_can_disable_price_limit_and_suspension_filters(self) -> None:
        from fintech_quant.backtesting import (
            AShareTradingConstraints,
            run_portfolio_scored_baseline_backtest,
        )

        bars = [_bar("000001.SZ", "2026-01-01", 10.0, is_suspended=True, limit_up=True)]
        scores = {(date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0)}

        result = run_portfolio_scored_baseline_backtest(
            bars,
            scores,
            initial_cash=100000.0,
            constraints=AShareTradingConstraints(
                price_limit_required=False, suspension_filter_required=False
            ),
        )

        self.assertEqual([trade.action for trade in result.trades], [TradeAction.BUY])

    def test_portfolio_runner_keeps_function_lot_size_when_constraints_are_passed(self) -> None:
        from fintech_quant.backtesting import (
            AShareTradingConstraints,
            run_portfolio_scored_baseline_backtest,
        )

        bars = [_bar("000001.SZ", "2026-01-01", 10.0, limit_up=True)]
        scores = {(date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0)}

        result = run_portfolio_scored_baseline_backtest(
            bars,
            scores,
            initial_cash=100000.0,
            lot_size=300,
            constraints=AShareTradingConstraints(price_limit_required=False),
        )

        self.assertEqual(result.trades[0].shares, 600)

    def test_portfolio_runner_liquidates_on_portfolio_drawdown_risk(self) -> None:
        from fintech_quant.backtesting import run_portfolio_scored_baseline_backtest

        bars = [
            _bar("000001.SZ", "2026-01-01", 10.0),
            _bar("000001.SZ", "2026-01-02", 8.0),
        ]
        scores = {
            (date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0),
            (date(2026, 1, 2), "000001.SZ"): _score("000001.SZ", 80.0),
        }
        risk_inputs = {(date(2026, 1, 2), "000001.SZ"): RiskInput(portfolio_drawdown=0.15)}

        result = run_portfolio_scored_baseline_backtest(
            bars, scores, risk_inputs=risk_inputs, initial_cash=100000.0
        )

        self.assertEqual(result.trades[-1].action, TradeAction.SELL)
        self.assertEqual(result.trades[-1].shares, 800)
        self.assertIn("portfolio_drawdown", [warning.rule for warning in result.risk_warnings])
        self.assertGreaterEqual(result.summary["risk_warning_count"], 1)

    def test_portfolio_runner_does_not_sell_limit_down_stock(self) -> None:
        from fintech_quant.backtesting import run_portfolio_scored_baseline_backtest

        bars = [
            _bar("000001.SZ", "2026-01-01", 10.0),
            _bar("000001.SZ", "2026-01-02", 8.0, limit_down=True),
        ]
        scores = {
            (date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0),
            (date(2026, 1, 2), "000001.SZ"): _score("000001.SZ", 80.0),
        }
        risk_inputs = {(date(2026, 1, 2), "000001.SZ"): RiskInput(portfolio_drawdown=0.15)}

        result = run_portfolio_scored_baseline_backtest(
            bars, scores, risk_inputs=risk_inputs, initial_cash=100000.0
        )

        self.assertEqual([trade.action for trade in result.trades], [TradeAction.BUY])
        self.assertIn("portfolio_drawdown", [warning.rule for warning in result.risk_warnings])

    def test_portfolio_runner_records_realized_pnl_on_sell_trades(self) -> None:
        from fintech_quant.backtesting import run_portfolio_scored_baseline_backtest

        bars = [
            _bar("000001.SZ", "2026-01-01", 10.0),
            _bar("000001.SZ", "2026-01-02", 12.0),
        ]
        scores = {
            (date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0),
            (date(2026, 1, 2), "000001.SZ"): _score("000001.SZ", 80.0),
        }
        risk_inputs = {(date(2026, 1, 2), "000001.SZ"): RiskInput(portfolio_drawdown=0.15)}

        result = run_portfolio_scored_baseline_backtest(
            bars,
            scores,
            risk_inputs=risk_inputs,
            initial_cash=10000.0,
            max_position_weight=1.0,
            commission_rate=0.0,
        )

        self.assertEqual(
            [trade.action for trade in result.trades], [TradeAction.BUY, TradeAction.SELL]
        )
        self.assertIsNone(result.trades[0].realized_pnl)
        self.assertEqual(result.trades[1].realized_pnl, 2000.0)
        self.assertEqual(result.summary["win_rate"], 1.0)
        self.assertEqual(result.summary["win_rate_basis"], "closed_trades_realized_pnl")
        self.assertEqual(result.summary["win_rate_sample_count"], 1)

    def test_portfolio_runner_does_not_sell_suspended_stock(self) -> None:
        from fintech_quant.backtesting import run_portfolio_scored_baseline_backtest

        bars = [
            _bar("000001.SZ", "2026-01-01", 10.0),
            _bar("000001.SZ", "2026-01-02", 8.0, is_suspended=True),
        ]
        scores = {
            (date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0),
            (date(2026, 1, 2), "000001.SZ"): _score("000001.SZ", 80.0),
        }
        risk_inputs = {(date(2026, 1, 2), "000001.SZ"): RiskInput(portfolio_drawdown=0.15)}

        result = run_portfolio_scored_baseline_backtest(
            bars, scores, risk_inputs=risk_inputs, initial_cash=100000.0
        )

        self.assertEqual([trade.action for trade in result.trades], [TradeAction.BUY])
        self.assertIn("portfolio_drawdown", [warning.rule for warning in result.risk_warnings])

    def test_portfolio_runner_liquidates_when_actual_portfolio_drawdown_crosses_threshold(
        self,
    ) -> None:
        from fintech_quant.backtesting import run_portfolio_scored_baseline_backtest

        bars = [
            _bar("000001.SZ", "2026-01-01", 10.0),
            _bar("000001.SZ", "2026-01-02", 8.0),
        ]
        scores = {
            (date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0),
            (date(2026, 1, 2), "000001.SZ"): _score("000001.SZ", 80.0),
        }

        result = run_portfolio_scored_baseline_backtest(
            bars,
            scores,
            initial_cash=10000.0,
            max_position_weight=1.0,
        )

        self.assertEqual(
            [trade.action for trade in result.trades], [TradeAction.BUY, TradeAction.SELL]
        )
        self.assertIn("portfolio_drawdown", [warning.rule for warning in result.risk_warnings])

    def test_portfolio_runner_reduces_when_actual_single_position_drawdown_crosses_threshold(
        self,
    ) -> None:
        from fintech_quant.backtesting import run_portfolio_scored_baseline_backtest

        bars = [
            _bar("000001.SZ", "2026-01-01", 10.0),
            _bar("000001.SZ", "2026-01-02", 9.0),
        ]
        scores = {
            (date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0),
            (date(2026, 1, 2), "000001.SZ"): _score("000001.SZ", 80.0),
        }

        result = run_portfolio_scored_baseline_backtest(
            bars,
            scores,
            initial_cash=10000.0,
            max_position_weight=1.0,
        )

        self.assertEqual(
            [trade.action for trade in result.trades], [TradeAction.BUY, TradeAction.SELL]
        )
        self.assertEqual(result.risk_warnings[-1].rule, "single_position_drawdown")

    def test_portfolio_runner_uses_configured_position_weight_limit_for_dynamic_risk(self) -> None:
        from fintech_quant.backtesting import run_portfolio_scored_baseline_backtest

        bars = [
            _bar("000001.SZ", "2026-01-01", 10.0),
            _bar("000001.SZ", "2026-01-02", 10.0),
        ]
        scores = {
            (date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0),
            (date(2026, 1, 2), "000001.SZ"): _score("000001.SZ", 80.0),
        }

        result = run_portfolio_scored_baseline_backtest(
            bars,
            scores,
            initial_cash=10000.0,
            max_position_weight=1.0,
        )

        self.assertEqual([trade.action for trade in result.trades], [TradeAction.BUY])
        self.assertNotIn("position_weight", [warning.rule for warning in result.risk_warnings])

    def test_portfolio_runner_uses_custom_risk_limits_for_static_warnings(self) -> None:
        from fintech_quant.backtesting import run_portfolio_scored_baseline_backtest
        from fintech_quant.risk import RiskLimits

        bars = [_bar("000001.SZ", "2026-01-01", 10.0)]
        scores = {(date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0)}
        risk_inputs = {(date(2026, 1, 1), "000001.SZ"): RiskInput(main_outflow_days=3)}

        result = run_portfolio_scored_baseline_backtest(
            bars,
            scores,
            risk_inputs=risk_inputs,
            risk_limits=RiskLimits(max_main_outflow_days=2),
            initial_cash=100000.0,
        )

        self.assertIn("main_outflow_days", [warning.rule for warning in result.risk_warnings])

    def test_custom_risk_limits_keep_configured_position_weight_limit(self) -> None:
        from fintech_quant.backtesting import run_portfolio_scored_baseline_backtest
        from fintech_quant.risk import RiskLimits

        bars = [
            _bar("000001.SZ", "2026-01-01", 10.0),
            _bar("000001.SZ", "2026-01-02", 10.0),
        ]
        scores = {
            (date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0),
            (date(2026, 1, 2), "000001.SZ"): _score("000001.SZ", 80.0),
        }

        result = run_portfolio_scored_baseline_backtest(
            bars,
            scores,
            risk_limits=RiskLimits(max_main_outflow_days=2),
            initial_cash=10000.0,
            max_position_weight=1.0,
        )

        self.assertNotIn("position_weight", [warning.rule for warning in result.risk_warnings])

    def test_portfolio_runner_does_not_false_sell_flat_default_position_after_commission(
        self,
    ) -> None:
        from fintech_quant.backtesting import run_portfolio_scored_baseline_backtest

        bars = [
            _bar("000001.SZ", "2026-01-01", 10.0),
            _bar("000001.SZ", "2026-01-02", 10.0),
        ]
        scores = {
            (date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0),
            (date(2026, 1, 2), "000001.SZ"): _score("000001.SZ", 80.0),
        }

        result = run_portfolio_scored_baseline_backtest(bars, scores, initial_cash=100000.0)

        self.assertEqual([trade.action for trade in result.trades], [TradeAction.BUY])
        self.assertNotIn("position_weight", [warning.rule for warning in result.risk_warnings])

    def test_portfolio_runner_sells_held_position_on_dynamic_risk_without_same_day_score(
        self,
    ) -> None:
        from fintech_quant.backtesting import run_portfolio_scored_baseline_backtest

        bars = [
            _bar("000001.SZ", "2026-01-01", 10.0),
            _bar("000001.SZ", "2026-01-02", 8.0),
        ]
        scores = {
            (date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0),
        }

        result = run_portfolio_scored_baseline_backtest(
            bars,
            scores,
            initial_cash=10000.0,
            max_position_weight=1.0,
        )

        self.assertEqual(
            [trade.action for trade in result.trades], [TradeAction.BUY, TradeAction.SELL]
        )
        self.assertIn("portfolio_drawdown", [warning.rule for warning in result.risk_warnings])

    def test_portfolio_runner_liquidates_multiple_positions_on_actual_portfolio_drawdown(
        self,
    ) -> None:
        from fintech_quant.backtesting import run_portfolio_scored_baseline_backtest

        bars = [
            _bar("000001.SZ", "2026-01-01", 10.0),
            _bar("000002.SZ", "2026-01-01", 10.0),
            _bar("000001.SZ", "2026-01-02", 8.0),
            _bar("000002.SZ", "2026-01-02", 8.0),
        ]
        scores = {
            (date(2026, 1, 1), "000001.SZ"): _score("000001.SZ", 80.0),
            (date(2026, 1, 1), "000002.SZ"): _score("000002.SZ", 80.0),
            (date(2026, 1, 2), "000001.SZ"): _score("000001.SZ", 80.0),
            (date(2026, 1, 2), "000002.SZ"): _score("000002.SZ", 80.0),
        }

        result = run_portfolio_scored_baseline_backtest(
            bars,
            scores,
            initial_cash=10000.0,
            max_position_weight=0.5,
        )

        self.assertEqual(
            [trade.action for trade in result.trades],
            [TradeAction.BUY, TradeAction.BUY, TradeAction.SELL, TradeAction.SELL],
        )
        self.assertEqual(
            [trade.symbol for trade in result.trades if trade.action is TradeAction.SELL],
            ["000001.SZ", "000002.SZ"],
        )
        self.assertIn("portfolio_drawdown", [warning.rule for warning in result.risk_warnings])


def _bar(symbol: str, trade_date: str, close: float, **overrides: object) -> dict[str, object]:
    row = {
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
    row.update(overrides)
    return row


def _score(symbol: str, total: float) -> StockScore:
    return StockScore(
        symbol=symbol,
        total=total,
        components={
            "fundamental": ComponentScore("fundamental", 35.0, 35.0, ()),
            "technical": ComponentScore("technical", 25.0, 25.0, ()),
            "capital_flow": ComponentScore("capital_flow", 25.0, 25.0, ()),
            "sentiment": ComponentScore("sentiment", 15.0, 15.0, ()),
        },
        confidence=1.0,
        missing_fields=(),
    )


if __name__ == "__main__":
    unittest.main()
