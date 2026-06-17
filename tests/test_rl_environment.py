from __future__ import annotations

import unittest

import pandas as pd


class RlEnvironmentTest(unittest.TestCase):
    def test_reset_returns_observation_and_step_buy_changes_reward(self) -> None:
        from fintech_quant.training.rl_environment import AShareBuySellHoldEnvironment

        features = pd.DataFrame(
            {
                "代码": ["sh688001", "sh688001", "sh688001"],
                "date": ["2024-01-02", "2024-01-03", "2024-01-04"],
                "close": [10.0, 11.0, 12.0],
                "return_1d": [0.0, 0.1, 0.0909],
                "rsi_14": [50.0, 60.0, 70.0],
            }
        )
        env = AShareBuySellHoldEnvironment(
            features=features,
            feature_columns=["close", "return_1d", "rsi_14"],
            initial_cash=10_000.0,
            target_weight=0.5,
            commission_rate=0.0,
            stamp_tax_rate=0.0,
            slippage_rate=0.0,
        )

        observation, info = env.reset()
        self.assertEqual(observation, [10.0, 0.0, 50.0])
        self.assertEqual(info["date"], "2024-01-02")

        next_observation, reward, terminated, truncated, info = env.step(1)

        self.assertEqual(next_observation, [11.0, 0.1, 60.0])
        self.assertAlmostEqual(reward, 500.0)
        self.assertFalse(terminated)
        self.assertFalse(truncated)
        self.assertEqual(info["action"], "buy")

    def test_environment_terminates_after_last_row(self) -> None:
        from fintech_quant.training.rl_environment import AShareBuySellHoldEnvironment

        features = pd.DataFrame(
            {
                "代码": ["sh688001", "sh688001"],
                "date": ["2024-01-02", "2024-01-03"],
                "close": [10.0, 10.0],
            }
        )
        env = AShareBuySellHoldEnvironment(features=features, feature_columns=["close"])
        env.reset()

        _, _, terminated, truncated, _ = env.step(0)

        self.assertTrue(terminated)
        self.assertFalse(truncated)

    def test_environment_blocks_buy_above_max_position_weight(self) -> None:
        from fintech_quant.training.rl_environment import AShareBuySellHoldEnvironment

        features = pd.DataFrame(
            {
                "代码": ["sh688001", "sh688001"],
                "date": ["2024-01-02", "2024-01-03"],
                "close": [10.0, 11.0],
            }
        )
        env = AShareBuySellHoldEnvironment(
            features=features,
            feature_columns=["close"],
            initial_cash=10_000.0,
            target_weight=0.5,
            max_position_weight=0.1,
        )
        env.reset()

        _, reward, _, _, info = env.step(1)

        self.assertAlmostEqual(reward, 0.0)
        self.assertEqual(info["position_quantity"], 0)


if __name__ == "__main__":
    unittest.main()
