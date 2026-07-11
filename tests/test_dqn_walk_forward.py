from __future__ import annotations

import importlib.util
import unittest
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fintech_quant.training import RlStateSample


class DqnWalkForwardTest(unittest.TestCase):
    def test_rolling_windows_do_not_overlap(self) -> None:
        from fintech_quant.training.dqn_walk_forward import rolling_dqn_windows

        samples = [
            _sample("2020-01-01"),
            _sample("2020-12-31"),
            _sample("2021-01-01"),
            _sample("2021-12-31"),
            _sample("2022-01-01"),
            _sample("2022-12-31"),
            _sample("2023-01-01"),
            _sample("2023-12-31"),
        ]

        windows = rolling_dqn_windows(samples, train_years=2, eval_years=1)

        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0].train_start.isoformat(), "2020-01-01")
        self.assertEqual(windows[0].train_end.isoformat(), "2021-12-31")
        self.assertEqual(windows[0].eval_start.isoformat(), "2022-01-01")
        self.assertEqual(windows[0].eval_end.isoformat(), "2022-12-31")
        self.assertLess(windows[0].train_end, windows[0].eval_start)

    def test_walk_forward_report_runs_when_torch_backend_is_available(self) -> None:
        from fintech_quant.backtesting import DrawdownControlPolicy
        from fintech_quant.training.dqn_walk_forward import run_torch_dqn_walk_forward_report
        from fintech_quant.training.torch_dqn import TorchDQNConfig

        samples = [
            _sample("2020-01-01", next_trade_date="2020-01-02"),
            _sample("2020-01-02", next_trade_date="2020-01-03"),
            _sample("2021-01-01", next_trade_date="2021-01-02"),
            _sample("2021-01-02", next_trade_date="2021-01-03"),
            _sample("2021-12-30", next_trade_date="2021-12-31"),
            _sample("2021-12-31", next_trade_date="2021-12-31"),
        ]

        if importlib.util.find_spec("torch") is None:
            with self.assertRaisesRegex(RuntimeError, "PyTorch is required"):
                run_torch_dqn_walk_forward_report(
                    samples,
                    config=TorchDQNConfig(episodes=1, batch_size=2),
                    drawdown_policy=DrawdownControlPolicy(),
                    train_years=1,
                    eval_years=1,
                )
            return

        report = run_torch_dqn_walk_forward_report(
            samples,
            config=TorchDQNConfig(episodes=1, batch_size=1),
            drawdown_policy=DrawdownControlPolicy(),
            train_years=1,
            eval_years=1,
        )

        self.assertEqual(report["policy"], "torch_dqn_v1")
        self.assertEqual(report["summary"]["window_count"], 1)
        self.assertIn("drawdown_control", report["windows"][0]["evaluation"])

    def test_walk_forward_report_requires_torch_backend(self) -> None:
        if importlib.util.find_spec("torch") is not None:
            self.skipTest("torch is installed")

        from fintech_quant.training.dqn_walk_forward import run_torch_dqn_walk_forward_report
        from fintech_quant.training.torch_dqn import TorchDQNConfig

        samples = [
            _sample("2020-01-01", next_trade_date="2020-01-02"),
            _sample("2020-01-02", next_trade_date="2020-01-03"),
            _sample("2021-01-01", next_trade_date="2021-01-02"),
            _sample("2021-01-02", next_trade_date="2021-01-03"),
            _sample("2021-12-30", next_trade_date="2021-12-31"),
            _sample("2021-12-31", next_trade_date="2021-12-31"),
        ]

        with self.assertRaisesRegex(RuntimeError, "PyTorch is required"):
            run_torch_dqn_walk_forward_report(
                samples,
                config=TorchDQNConfig(episodes=1, batch_size=2),
                train_years=1,
                eval_years=1,
            )

    def test_slice_window_excludes_forward_returns_that_cross_window_boundaries(self) -> None:
        from fintech_quant.training.dqn_walk_forward import DqnWalkForwardWindow, slice_dqn_window

        samples = [
            _sample("2020-12-30", next_trade_date="2020-12-31"),
            _sample("2020-12-31", next_trade_date="2021-01-01"),
            _sample("2021-12-30", next_trade_date="2021-12-31"),
            _sample("2021-12-31", next_trade_date="2022-01-01"),
        ]
        window = DqnWalkForwardWindow(
            name="rolling_1",
            train_start=date.fromisoformat("2020-01-01"),
            train_end=date.fromisoformat("2020-12-31"),
            eval_start=date.fromisoformat("2021-01-01"),
            eval_end=date.fromisoformat("2021-12-31"),
        )

        train, evaluation = slice_dqn_window(samples, window)

        self.assertEqual([sample.trade_date.isoformat() for sample in train], ["2020-12-30"])
        self.assertEqual([sample.trade_date.isoformat() for sample in evaluation], ["2021-12-30"])


def _sample(trade_date: str, next_trade_date: str | None = None) -> "RlStateSample":
    from fintech_quant.training import RlStateSample

    current = date.fromisoformat(trade_date)
    following = date.fromisoformat(next_trade_date) if next_trade_date else current
    return RlStateSample(
        "000001.SZ",
        current,
        following,
        ("signal",),
        (1.0,),
        0.01,
    )


if __name__ == "__main__":
    unittest.main()
