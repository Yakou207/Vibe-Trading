from __future__ import annotations

import unittest
from datetime import date


class RlEnvironmentTest(unittest.TestCase):
    def test_reset_returns_first_state_with_position_feature(self) -> None:
        from fintech_quant.training import AShareBuySellHoldEnvironment

        env = AShareBuySellHoldEnvironment(_samples())

        observation = env.reset()

        self.assertEqual(env.observation_fields, ("feature", "position"))
        self.assertEqual(observation, (1.0, 0.0))

    def test_buy_sell_steps_apply_forward_return_costs_and_done_state(self) -> None:
        from fintech_quant.training import AShareBuySellHoldEnvironment

        env = AShareBuySellHoldEnvironment(_samples(), transaction_cost=0.001)
        env.reset()

        first = env.step("buy")
        second = env.step("sell")

        self.assertEqual(first.observation, (2.0, 1.0))
        self.assertAlmostEqual(first.reward, 0.099)
        self.assertFalse(first.done)
        self.assertEqual(first.info["position"], 1)
        self.assertAlmostEqual(first.info["equity"], 1.099)
        self.assertAlmostEqual(first.info["transaction_cost"], 0.001)

        self.assertIsNone(second.observation)
        self.assertAlmostEqual(second.reward, -0.001)
        self.assertTrue(second.done)
        self.assertEqual(second.info["position"], 0)
        self.assertAlmostEqual(second.info["equity"], 1.097901)
        self.assertAlmostEqual(second.info["transaction_cost"], 0.001)

    def test_environment_accepts_trade_action_values(self) -> None:
        from fintech_quant.training import AShareBuySellHoldEnvironment
        from fintech_quant.trading import TradeAction

        env = AShareBuySellHoldEnvironment(_samples(), transaction_cost=0.0)
        env.reset()

        step = env.step(TradeAction.BUY)

        self.assertEqual(step.info["action"], "buy")
        self.assertEqual(step.info["position"], 1)

    def test_environment_rejects_empty_samples_and_invalid_actions(self) -> None:
        from fintech_quant.training import AShareBuySellHoldEnvironment

        with self.assertRaisesRegex(ValueError, "samples"):
            AShareBuySellHoldEnvironment([])

        env = AShareBuySellHoldEnvironment(_samples())
        env.reset()

        with self.assertRaisesRegex(ValueError, "action"):
            env.step("short")

    def test_environment_rejects_multi_symbol_samples(self) -> None:
        from fintech_quant.training import AShareBuySellHoldEnvironment

        samples = _samples()
        samples[1] = _sample(symbol="600000.SH", feature=2.0, forward_return=-0.05, terminal=True)

        with self.assertRaisesRegex(ValueError, "single symbol"):
            AShareBuySellHoldEnvironment(samples)

    def test_terminal_sample_ends_episode_before_next_observation(self) -> None:
        from fintech_quant.training import AShareBuySellHoldEnvironment

        samples = [
            _sample(feature=1.0, forward_return=0.1, terminal=True),
            _sample(feature=2.0, forward_return=-0.05),
        ]
        env = AShareBuySellHoldEnvironment(samples)
        env.reset()

        step = env.step("buy")

        self.assertTrue(step.done)
        self.assertIsNone(step.observation)

    def test_step_after_done_requires_reset(self) -> None:
        from fintech_quant.training import AShareBuySellHoldEnvironment

        env = AShareBuySellHoldEnvironment([_sample(feature=1.0, forward_return=0.1, terminal=True)])
        env.reset()
        env.step("hold")

        with self.assertRaisesRegex(RuntimeError, "reset"):
            env.step("hold")


def _samples() -> list[object]:
    return [
        _sample(feature=1.0, forward_return=0.10),
        _sample(feature=2.0, forward_return=-0.05, terminal=True),
    ]


def _sample(
    *,
    symbol: str = "000001.SZ",
    feature: float,
    forward_return: float,
    terminal: bool = False,
) -> object:
    from fintech_quant.training import RlStateSample

    day = 1 if feature == 1.0 else 2
    return RlStateSample(
        symbol=symbol,
        trade_date=date(2026, 1, day),
        next_trade_date=date(2026, 1, day + 1),
        state_fields=("feature",),
        state_vector=(feature,),
        forward_return_1d=forward_return,
        terminal=terminal,
    )


if __name__ == "__main__":
    unittest.main()
