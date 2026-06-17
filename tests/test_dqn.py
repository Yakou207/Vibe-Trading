from __future__ import annotations

import unittest

import pandas as pd


class DQNTest(unittest.TestCase):
    def test_dqn_config_decays_epsilon_to_floor(self) -> None:
        from fintech_quant.training.dqn import DQNConfig

        config = DQNConfig(epsilon=0.8, min_epsilon=0.1, epsilon_decay=0.5)

        self.assertAlmostEqual(config.exploration_rate(0), 0.8)
        self.assertAlmostEqual(config.exploration_rate(1), 0.4)
        self.assertAlmostEqual(config.exploration_rate(4), 0.1)

    def test_dqn_strategy_returns_trade_decision(self) -> None:
        from fintech_quant.training.dqn import DQNConfig, DQNStrategy, train_dqn
        from fintech_quant.trading import TradeAction

        frame = pd.DataFrame(
            {
                "代码": ["sh688001", "sh688001", "sh688001", "sh688001"],
                "date": ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
                "close": [10.0, 10.5, 11.0, 10.8],
                "rsi_14": [45.0, 55.0, 65.0, 50.0],
                "macd_hist": [0.1, 0.2, 0.1, -0.1],
                "return_5d": [0.01, 0.02, 0.03, -0.01],
                "return_20d": [0.01, 0.02, 0.03, -0.01],
                "close_to_ma_20": [1.0, 1.01, 1.02, 0.99],
                "ma_20_slope": [0.01, 0.01, 0.02, 0.0],
                "volatility_20": [0.02, 0.02, 0.03, 0.03],
                "target_next_return_1d": [0.05, 0.04, -0.02, 0.0],
            }
        )

        model = train_dqn(frame, DQNConfig(episodes=1, batch_size=2, seed=1))
        strategy = DQNStrategy(model=model, target_weight=0.25)

        decision = strategy.decide({**frame.iloc[0].to_dict(), "position_quantity": 0})

        self.assertIn(decision.action, {TradeAction.HOLD, TradeAction.BUY, TradeAction.SELL})
        self.assertIn("DQN", decision.reason)


if __name__ == "__main__":
    unittest.main()
