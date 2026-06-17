from __future__ import annotations

from dataclasses import asdict

import pandas as pd

from fintech_quant.backtesting.engine import BacktestConfig, run_daily_backtest
from fintech_quant.strategies.buy_and_hold import EqualWeightBuyAndHoldStrategy
from fintech_quant.training.q_learning import QLearningConfig, QLearningStrategy, train_q_learning
from fintech_quant.training.walk_forward import rolling_windows, slice_window


def run_q_learning_walk_forward_report(
    features: pd.DataFrame,
    q_config: QLearningConfig | None = None,
    train_years: int = 2,
    test_years: int = 1,
    initial_cash: float = 1_000_000.0,
    target_weight: float = 0.1,
    max_position_weight: float = 0.1,
    max_portfolio_drawdown: float = 0.2,
    commission_rate: float = 0.0003,
    stamp_tax_rate: float = 0.001,
    slippage_rate: float = 0.0005,
) -> dict[str, object]:
    q_config = q_config or QLearningConfig()
    dates = pd.to_datetime(features["date"])
    windows = rolling_windows(dates, train_years=train_years, test_years=test_years)
    backtest_config = BacktestConfig(
        initial_cash=initial_cash,
        max_position_weight=max_position_weight,
        max_portfolio_drawdown=max_portfolio_drawdown,
        commission_rate=commission_rate,
        stamp_tax_rate=stamp_tax_rate,
        slippage_rate=slippage_rate,
    )
    window_payloads: list[dict[str, object]] = []

    for window in windows:
        train, test = slice_window(features, window)
        if train.empty or test.empty:
            continue
        model = train_q_learning(train, q_config)
        rl_result = run_daily_backtest(
            features=test,
            strategy=QLearningStrategy(model=model, target_weight=target_weight),
            config=backtest_config,
        )
        buy_hold_result = run_daily_backtest(
            features=test,
            strategy=EqualWeightBuyAndHoldStrategy(target_weight=target_weight),
            config=backtest_config,
        )
        rl_metrics = asdict(rl_result.metrics)
        buy_hold_metrics = asdict(buy_hold_result.metrics)
        window_payloads.append(
            {
                "window_name": window.name,
                "train_start": window.train_start.isoformat(),
                "train_end": window.train_end.isoformat(),
                "test_start": window.test_start.isoformat(),
                "test_end": window.test_end.isoformat(),
                "train_rows": len(train),
                "test_rows": len(test),
                "q_state_count": _q_state_count(model.q_table),
                "rl_metrics": rl_metrics,
                "buy_hold_metrics": buy_hold_metrics,
                "excess_total_return": round(
                    rl_metrics["total_return"] - buy_hold_metrics["total_return"],
                    10,
                ),
            }
        )

    return {
        "strategy": "q_learning_v1",
        "baseline": "equal_weight_buy_and_hold",
        "validation": {
            "mode": "rolling_walk_forward",
            "train_years": train_years,
            "test_years": test_years,
            "look_ahead_bias_control": (
                "State bins and Q-table are fit only on each train window; "
                "RL and buy-and-hold are backtested on the same held-out test rows."
            ),
        },
        "q_learning": asdict(q_config),
        "windows": window_payloads,
    }


def _q_state_count(q_table: dict[object, float]) -> int:
    return len({key[0] for key in q_table})
