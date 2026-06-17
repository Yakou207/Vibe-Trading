from __future__ import annotations

import unittest


class PortfolioExecutionTest(unittest.TestCase):
    def test_buy_order_pays_commission_slippage_and_rounds_to_lot_size(self) -> None:
        from fintech_quant.backtesting.costs import CostModel
        from fintech_quant.backtesting.portfolio import Order, Portfolio

        portfolio = Portfolio(initial_cash=10_000.0, cost_model=CostModel(commission_rate=0.001))

        trade = portfolio.buy(
            Order(symbol="sh688001", date="2024-01-02", quantity=150, price=10.0),
            lot_size=100,
        )

        self.assertIsNotNone(trade)
        self.assertEqual(trade.quantity, 100)
        self.assertAlmostEqual(trade.cash_delta, -1001.0)
        self.assertAlmostEqual(portfolio.cash, 8999.0)
        self.assertEqual(portfolio.position_quantity("sh688001"), 100)
        self.assertEqual(portfolio.sellable_quantity("sh688001"), 0)

    def test_sell_order_pays_commission_stamp_tax_slippage_and_respects_t_plus_one(self) -> None:
        from fintech_quant.backtesting.costs import CostModel
        from fintech_quant.backtesting.portfolio import Order, Portfolio

        portfolio = Portfolio(
            initial_cash=10_000.0,
            cost_model=CostModel(commission_rate=0.001, stamp_tax_rate=0.001),
        )
        portfolio.buy(Order("sh688001", "2024-01-02", 100, 10.0), lot_size=100)

        blocked = portfolio.sell(Order("sh688001", "2024-01-02", 100, 11.0), lot_size=100)
        self.assertIsNone(blocked)

        portfolio.close_trading_day("2024-01-02")
        trade = portfolio.sell(Order("sh688001", "2024-01-03", 100, 11.0), lot_size=100)

        self.assertIsNotNone(trade)
        self.assertAlmostEqual(trade.cash_delta, 1097.8)
        self.assertEqual(portfolio.position_quantity("sh688001"), 0)

    def test_risk_gate_blocks_oversized_buy_and_drawdown_stop(self) -> None:
        from fintech_quant.backtesting.costs import CostModel
        from fintech_quant.backtesting.portfolio import Order, Portfolio
        from fintech_quant.risk.rules import RiskGate, RiskLimits

        portfolio = Portfolio(initial_cash=10_000.0, cost_model=CostModel())
        gate = RiskGate(RiskLimits(max_position_weight=0.2, max_portfolio_drawdown=0.1))

        oversized = gate.evaluate_buy(
            portfolio=portfolio,
            order=Order("sh688001", "2024-01-02", 300, 10.0),
            lot_size=100,
            latest_prices={"sh688001": 10.0},
        )
        self.assertFalse(oversized.allowed)
        self.assertIn("position weight", oversized.reason)

        portfolio.record_snapshot("2024-01-02", {"sh688001": 10.0})
        portfolio.record_snapshot("2024-01-03", {"sh688001": 8.0}, external_equity=8_900.0)
        stopped = gate.evaluate_buy(
            portfolio=portfolio,
            order=Order("sh688001", "2024-01-04", 100, 8.0),
            lot_size=100,
            latest_prices={"sh688001": 8.0},
        )
        self.assertFalse(stopped.allowed)
        self.assertIn("drawdown", stopped.reason)


if __name__ == "__main__":
    unittest.main()
