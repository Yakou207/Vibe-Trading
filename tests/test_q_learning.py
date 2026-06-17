from __future__ import annotations

import unittest

import pandas as pd


class QLearningTest(unittest.TestCase):
    def test_q_learning_config_decays_epsilon_for_greedy_exploitation(self) -> None:
        from fintech_quant.training.q_learning import QLearningConfig

        config = QLearningConfig(epsilon=0.5, min_epsilon=0.1, epsilon_decay=0.5)

        self.assertAlmostEqual(config.exploration_rate(episode=0), 0.5)
        self.assertAlmostEqual(config.exploration_rate(episode=1), 0.25)
        self.assertAlmostEqual(config.exploration_rate(episode=3), 0.1)

    def test_state_binner_fits_thresholds_from_train_frame(self) -> None:
        from fintech_quant.training.q_learning import StateBinner

        train = pd.DataFrame(
            {
                "rsi_14": [20.0, 50.0, 80.0],
                "macd_hist": [-0.2, 0.0, 0.2],
                "return_20d": [-0.10, 0.0, 0.10],
                "close_to_ma_20": [-0.20, 0.0, 0.20],
                "ma_20_slope": [-0.05, 0.0, 0.05],
                "volatility_20": [0.01, 0.02, 0.03],
            }
        )

        binner = StateBinner.fit(train)
        state = binner.transform_row(
            {
                "rsi_14": 75.0,
                "macd_hist": 0.5,
                "return_20d": 0.2,
                "close_to_ma_20": 0.2,
                "ma_20_slope": 0.1,
                "volatility_20": 0.04,
            },
            position_flag=1,
        )

        self.assertEqual(
            state,
            ("rsi_high", "macd_positive", "trend_up", "price_above_ma", "slope_up", "vol_high", 1),
        )

    def test_drawdown_penalty_reduces_reward_after_equity_drop(self) -> None:
        from fintech_quant.training.q_learning import training_reward
        from fintech_quant.trading import TradeAction

        penalized = training_reward(
            action=TradeAction.HOLD,
            position_flag=1,
            next_position_flag=1,
            next_return=0.01,
            trade_penalty=0.0,
            drawdown=0.20,
            drawdown_penalty=0.5,
        )

        self.assertAlmostEqual(penalized, -0.09)

    def test_q_learning_updates_profitable_buy_action(self) -> None:
        from fintech_quant.training.q_learning import QLearningConfig, train_q_learning
        from fintech_quant.trading import TradeAction

        frame = pd.DataFrame(
            {
                "代码": ["sh688001", "sh688001", "sh688001"],
                "date": ["2024-01-02", "2024-01-03", "2024-01-04"],
                "close": [10.0, 11.0, 12.0],
                "rsi_14": [75.0, 75.0, 75.0],
                "macd_hist": [0.1, 0.1, 0.1],
                "return_5d": [0.1, 0.1, 0.1],
                "return_20d": [0.1, 0.1, 0.1],
                "close_to_ma_20": [0.1, 0.1, 0.1],
                "ma_20_slope": [0.1, 0.1, 0.1],
                "volatility_20": [0.01, 0.01, 0.01],
                "target_next_return_1d": [0.10, 0.09, 0.0],
            }
        )

        model = train_q_learning(
            frame,
            QLearningConfig(episodes=5, epsilon=0.0, alpha=0.5, gamma=0.0, seed=1),
        )

        state = model.binner.transform_row(frame.iloc[0].to_dict(), position_flag=0)
        self.assertGreater(model.q_value(state, TradeAction.BUY), 0.0)

    def test_q_learning_strategy_selects_best_known_action(self) -> None:
        from fintech_quant.training.q_learning import QLearningConfig, QLearningStrategy, train_q_learning
        from fintech_quant.trading import TradeAction

        frame = pd.DataFrame(
            {
                "代码": ["sh688001", "sh688001"],
                "date": ["2024-01-02", "2024-01-03"],
                "close": [10.0, 11.0],
                "rsi_14": [80.0, 80.0],
                "macd_hist": [0.2, 0.2],
                "return_5d": [0.2, 0.2],
                "return_20d": [0.2, 0.2],
                "close_to_ma_20": [0.2, 0.2],
                "ma_20_slope": [0.2, 0.2],
                "volatility_20": [0.01, 0.01],
                "target_next_return_1d": [0.10, 0.0],
            }
        )
        model = train_q_learning(frame, QLearningConfig(episodes=3, epsilon=0.0, seed=1))
        strategy = QLearningStrategy(model=model, target_weight=0.25)

        decision = strategy.decide({**frame.iloc[0].to_dict(), "position_quantity": 0})

        self.assertEqual(decision.action, TradeAction.BUY)
        self.assertEqual(decision.confidence, 0.25)


if __name__ == "__main__":
    unittest.main()
