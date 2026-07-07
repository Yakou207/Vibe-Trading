from __future__ import annotations

import unittest
from datetime import date


class TorchDqnTrainingTest(unittest.TestCase):
    def test_torch_dqn_imports_and_reports_missing_dependency_cleanly(self) -> None:
        from fintech_quant.training import RlStateSample
        from fintech_quant.training.torch_dqn import TORCH_DQN_POLICY_NAME, TorchDQNConfig, train_torch_dqn_policy

        self.assertEqual(TORCH_DQN_POLICY_NAME, "torch_dqn_v1")

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
