from __future__ import annotations

import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace


class TorchDqnTrainingTest(unittest.TestCase):
    def test_torch_evaluation_uses_shared_portfolio_drawdown_state_machine(self) -> None:
        from fintech_quant.backtesting import DrawdownControlPolicy
        from fintech_quant.training import RlStateSample
        from fintech_quant.training.torch_dqn import evaluate_torch_dqn_policy

        class AlwaysBuyPolicy:
            config = SimpleNamespace(transaction_cost=0.0, drawdown_penalty=0.0)

            def action(self, _observation: object) -> str:
                return "buy"

        samples = [
            RlStateSample("000001.SZ", _date("2026-01-01"), _date("2026-01-02"), ("signal",), (1.0,), -0.08),
            RlStateSample("000001.SZ", _date("2026-01-02"), _date("2026-01-03"), ("signal",), (1.0,), -0.02),
            RlStateSample("000001.SZ", _date("2026-01-03"), _date("2026-01-04"), ("signal",), (1.0,), 0.055555),
        ]

        report = evaluate_torch_dqn_policy(
            samples,
            AlwaysBuyPolicy(),  # type: ignore[arg-type]
            drawdown_policy=DrawdownControlPolicy(),
        )

        self.assertEqual(report["summary"]["max_drawdown"], 0.0892)
        self.assertEqual(report["summary"]["action_counts"], {"buy": 3, "hold": 0, "sell": 0})
        self.assertEqual(
            [item["to_regime"] for item in report["drawdown_control"]["transitions"]],
            ["reduced", "normal"],
        )

    def test_torch_dqn_imports_and_trains_when_dependency_is_available(self) -> None:
        from fintech_quant.training import RlStateSample
        from fintech_quant.training.torch_dqn import TORCH_DQN_POLICY_NAME, TorchDQNConfig, train_torch_dqn_policy

        self.assertEqual(TORCH_DQN_POLICY_NAME, "torch_dqn_v1")

        samples = [
            RlStateSample("000001.SZ", _date("2026-01-01"), _date("2026-01-02"), ("signal",), (1.0,), 0.10),
            RlStateSample("000001.SZ", _date("2026-01-02"), _date("2026-01-03"), ("signal",), (-1.0,), -0.10),
        ]

        if importlib.util.find_spec("torch") is None:
            with self.assertRaisesRegex(RuntimeError, "PyTorch is required"):
                train_torch_dqn_policy(samples, TorchDQNConfig(episodes=1, batch_size=2))
            return

        policy = train_torch_dqn_policy(
            samples,
            TorchDQNConfig(episodes=1, batch_size=1, train_frequency=1),
        )

        self.assertEqual(policy.diagnostics()["type"], "torch_dqn_v1")
        self.assertEqual(policy.diagnostics()["training_steps"], 2)

    def test_torch_dqn_respects_configured_training_frequency(self) -> None:
        if importlib.util.find_spec("torch") is None:
            self.skipTest("torch is not installed")

        from fintech_quant.training import RlStateSample
        from fintech_quant.training.torch_dqn import TorchDQNConfig, train_torch_dqn_policy

        samples = [
            RlStateSample(
                "000001.SZ",
                _date(f"2026-01-{index:02d}"),
                _date(f"2026-01-{index + 1:02d}"),
                ("signal",),
                (1.0,),
                0.01,
            )
            for index in range(1, 9)
        ]

        policy = train_torch_dqn_policy(
            samples,
            TorchDQNConfig(episodes=1, batch_size=1, train_frequency=4),
        )

        self.assertEqual(policy.training_steps, 2)

    def test_torch_dqn_checkpoint_round_trips_and_resumes_training(self) -> None:
        if importlib.util.find_spec("torch") is None:
            self.skipTest("torch is not installed")

        from fintech_quant.training.dqn_checkpoint import (
            load_latest_torch_dqn_checkpoint,
            save_torch_dqn_checkpoint,
        )
        from fintech_quant.training import RlStateSample
        from fintech_quant.training.torch_dqn import TorchDQNConfig, train_torch_dqn_policy_run

        samples = [
            RlStateSample("000001.SZ", _date("2026-01-01"), _date("2026-01-02"), ("signal",), (1.0,), 0.10),
            RlStateSample("000001.SZ", _date("2026-01-02"), _date("2026-01-03"), ("signal",), (-1.0,), -0.10),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dqn"
            run = train_torch_dqn_policy_run(samples, TorchDQNConfig(episodes=1, batch_size=1))
            checkpoint = save_torch_dqn_checkpoint(
                run,
                root,
                checkpoint_id="unit",
                metadata={"source": "unit-test"},
            )
            loaded = load_latest_torch_dqn_checkpoint(root)
            resumed = train_torch_dqn_policy_run(
                samples,
                TorchDQNConfig(episodes=1, batch_size=1),
                initial_run=loaded,
            )

        self.assertEqual(checkpoint.name, "unit")
        self.assertEqual(loaded.metadata["source"], "unit-test")
        self.assertEqual(resumed.episodes_trained, loaded.episodes_trained + 1)
        self.assertGreaterEqual(resumed.policy.training_steps, loaded.policy.training_steps)

    def test_torch_dqn_reward_uses_benchmark_relative_excess_return(self) -> None:
        from fintech_quant.training.torch_dqn import _reward

        reward = _reward(
            next_position=1,
            forward_return=0.04,
            benchmark_return=0.06,
            changed_position=False,
            transaction_cost=0.0,
            drawdown=0.0,
            drawdown_penalty=0.0,
        )

        self.assertEqual(reward, -0.02)

    def test_torch_dqn_reports_missing_dependency_cleanly(self) -> None:
        if importlib.util.find_spec("torch") is not None:
            self.skipTest("torch is installed")

        from fintech_quant.training import RlStateSample
        from fintech_quant.training.torch_dqn import TorchDQNConfig, train_torch_dqn_policy

        samples = [
            RlStateSample("000001.SZ", _date("2026-01-01"), _date("2026-01-02"), ("signal",), (1.0,), 0.10),
            RlStateSample("000001.SZ", _date("2026-01-02"), _date("2026-01-03"), ("signal",), (-1.0,), -0.10),
        ]

        with self.assertRaisesRegex(RuntimeError, "PyTorch is required"):
            train_torch_dqn_policy(samples, TorchDQNConfig(episodes=1, batch_size=2))


def _date(value: str) -> date:
    return date.fromisoformat(value)


if __name__ == "__main__":
    unittest.main()
