import unittest


class ProjectContractsTest(unittest.TestCase):
    def test_default_settings_define_a_share_daily_research_scope(self) -> None:
        from fintech_quant.config import default_settings

        settings = default_settings()

        self.assertEqual(settings.market, "a_share")
        self.assertEqual(settings.frequency, "1d")
        self.assertEqual(settings.execution_mode, "paper")
        self.assertIn("akshare", settings.data_sources)
        self.assertIn("tushare", settings.data_sources)
        self.assertIn("yahoo", settings.data_sources)
        self.assertIn("finnhub", settings.data_sources)

    def test_trade_action_only_allows_buy_sell_hold(self) -> None:
        from fintech_quant.trading import TradeAction

        self.assertEqual(
            {action.value for action in TradeAction},
            {"buy", "sell", "hold"},
        )

    def test_rl_strategy_stub_returns_hold_until_training_exists(self) -> None:
        from fintech_quant.strategies.rl import RlBuySellHoldStrategy
        from fintech_quant.trading import TradeAction

        strategy = RlBuySellHoldStrategy(name="rl_bsh_v0")

        decision = strategy.decide({"symbol": "000001.SZ"})

        self.assertEqual(decision.action, TradeAction.HOLD)
        self.assertEqual(decision.confidence, 0.0)
        self.assertIn("untrained", decision.reason.lower())


if __name__ == "__main__":
    unittest.main()
