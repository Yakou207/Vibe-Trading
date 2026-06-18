from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

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

    def test_dqn_checkpoint_round_trip_preserves_policy_and_replay_buffer(self) -> None:
        from fintech_quant.training.dqn import DQNConfig, train_dqn_run
        from fintech_quant.training.dqn_checkpoint import load_dqn_checkpoint, save_dqn_checkpoint

        frame = _dqn_training_frame()
        run = train_dqn_run(
            frame,
            DQNConfig(episodes=1, batch_size=2, replay_capacity=8, seed=1),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_path = save_dqn_checkpoint(
                run,
                checkpoint_root=Path(tmpdir) / "dqn",
                checkpoint_id="run_001",
                metadata={"window_name": "fixture_window"},
                metrics={"sharpe_ratio": 1.25},
                max_checkpoints=10,
            )
            loaded = load_dqn_checkpoint(checkpoint_path)

            row = frame.iloc[0].to_dict()
            self.assertTrue((checkpoint_path / "model.pt").exists())
            self.assertTrue((checkpoint_path / "target_model.pt").exists())
            self.assertTrue((checkpoint_path / "optimizer.pt").exists())
            self.assertTrue((checkpoint_path / "replay_buffer.pkl").exists())
            self.assertEqual(loaded.episodes_trained, run.episodes_trained)
            self.assertEqual(len(loaded.replay), len(run.replay))
            self.assertEqual(loaded.model.scaler.columns, run.model.scaler.columns)
            self.assertEqual(loaded.metadata["window_name"], "fixture_window")
            self.assertEqual(loaded.metrics["sharpe_ratio"], 1.25)
            for left, right in zip(
                loaded.model.q_values(row, position_flag=0),
                run.model.q_values(row, position_flag=0),
                strict=True,
            ):
                self.assertAlmostEqual(left, right, places=6)

    def test_dqn_checkpoint_rotation_keeps_latest_ten_runs(self) -> None:
        from fintech_quant.training.dqn import DQNConfig, train_dqn_run
        from fintech_quant.training.dqn_checkpoint import save_dqn_checkpoint

        run = train_dqn_run(
            _dqn_training_frame(),
            DQNConfig(episodes=1, batch_size=2, replay_capacity=8, seed=1),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "dqn"
            for index in range(12):
                save_dqn_checkpoint(
                    run,
                    checkpoint_root=root,
                    checkpoint_id=f"run_{index:02d}",
                    max_checkpoints=10,
                )

            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["latest"], "run_11")
            self.assertEqual(len(manifest["checkpoints"]), 10)
            self.assertFalse((root / "checkpoints" / "run_00").exists())
            self.assertFalse((root / "checkpoints" / "run_01").exists())
            self.assertTrue((root / "checkpoints" / "run_02").exists())
            self.assertTrue((root / "checkpoints" / "run_11").exists())

    def test_dqn_resume_training_continues_from_loaded_checkpoint(self) -> None:
        from fintech_quant.training.dqn import DQNConfig, train_dqn_run
        from fintech_quant.training.dqn_checkpoint import load_dqn_checkpoint, save_dqn_checkpoint

        frame = _dqn_training_frame()
        config = DQNConfig(episodes=1, batch_size=2, replay_capacity=8, seed=1)
        first_run = train_dqn_run(frame, config)

        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_path = save_dqn_checkpoint(
                first_run,
                checkpoint_root=Path(tmpdir) / "dqn",
                checkpoint_id="run_001",
            )
            loaded = load_dqn_checkpoint(checkpoint_path)
            continued = train_dqn_run(frame, config, initial_run=loaded)

            self.assertEqual(continued.episodes_trained, first_run.episodes_trained + 1)
            self.assertGreaterEqual(
                continued.model.training_steps,
                first_run.model.training_steps,
            )
            self.assertGreater(len(continued.replay), 0)


def _dqn_training_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "代码": ["sh688001"] * 5,
            "date": [
                "2024-01-02",
                "2024-01-03",
                "2024-01-04",
                "2024-01-05",
                "2024-01-08",
            ],
            "close": [10.0, 10.5, 11.0, 10.8, 11.2],
            "rsi_14": [45.0, 55.0, 65.0, 50.0, 48.0],
            "macd_hist": [0.1, 0.2, 0.1, -0.1, 0.05],
            "return_5d": [0.01, 0.02, 0.03, -0.01, 0.02],
            "return_20d": [0.01, 0.02, 0.03, -0.01, 0.02],
            "close_to_ma_20": [1.0, 1.01, 1.02, 0.99, 1.01],
            "ma_20_slope": [0.01, 0.01, 0.02, 0.0, 0.01],
            "volatility_20": [0.02, 0.02, 0.03, 0.03, 0.02],
            "target_next_return_1d": [0.05, 0.04, -0.02, 0.03, 0.0],
        }
    )


if __name__ == "__main__":
    unittest.main()
