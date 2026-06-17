from __future__ import annotations

import html
from dataclasses import asdict

import pandas as pd

from fintech_quant.backtesting.engine import BacktestConfig, run_daily_backtest
from fintech_quant.strategies.buy_and_hold import EqualWeightBuyAndHoldStrategy
from fintech_quant.training.q_learning import QLearningConfig, QLearningStrategy, train_q_learning
from fintech_quant.training.walk_forward import rolling_windows, slice_window


def run_rl_stability_report(
    features: pd.DataFrame,
    seeds: list[int] | None = None,
    episode_counts: list[int] | None = None,
    train_years: int = 2,
    test_years: int = 1,
    initial_cash: float = 1_000_000.0,
    target_weight: float = 0.03,
    max_position_weight: float = 0.05,
    max_portfolio_drawdown: float = 0.2,
    commission_rate: float = 0.0003,
    stamp_tax_rate: float = 0.001,
    slippage_rate: float = 0.0005,
    alpha: float = 0.1,
    gamma: float = 0.95,
    epsilon: float = 0.2,
    min_epsilon: float = 0.05,
    epsilon_decay: float = 0.95,
    trade_penalty: float = 0.0005,
    drawdown_penalty: float = 0.2,
) -> dict[str, object]:
    seeds = seeds or [1, 7, 42]
    episode_counts = episode_counts or [25, 50, 100, 200]
    backtest_config = BacktestConfig(
        initial_cash=initial_cash,
        max_position_weight=max_position_weight,
        max_portfolio_drawdown=max_portfolio_drawdown,
        commission_rate=commission_rate,
        stamp_tax_rate=stamp_tax_rate,
        slippage_rate=slippage_rate,
    )
    windows = rolling_windows(pd.to_datetime(features["date"]), train_years, test_years)
    runs: list[dict[str, object]] = []

    for episodes in episode_counts:
        for seed in seeds:
            window_results = []
            for window in windows:
                train, test = slice_window(features, window)
                if train.empty or test.empty:
                    continue
                q_config = QLearningConfig(
                    episodes=episodes,
                    alpha=alpha,
                    gamma=gamma,
                    epsilon=epsilon,
                    min_epsilon=min_epsilon,
                    epsilon_decay=epsilon_decay,
                    trade_penalty=trade_penalty,
                    drawdown_penalty=drawdown_penalty,
                    seed=seed,
                )
                model = train_q_learning(train, q_config)
                rl_result = run_daily_backtest(
                    test,
                    QLearningStrategy(model=model, target_weight=target_weight),
                    backtest_config,
                )
                buy_hold_result = run_daily_backtest(
                    test,
                    EqualWeightBuyAndHoldStrategy(target_weight=target_weight),
                    backtest_config,
                )
                rl_metrics = asdict(rl_result.metrics)
                buy_hold_metrics = asdict(buy_hold_result.metrics)
                window_results.append(
                    {
                        "window_name": window.name,
                        "test_start": window.test_start.isoformat(),
                        "test_end": window.test_end.isoformat(),
                        "rl_metrics": rl_metrics,
                        "buy_hold_metrics": buy_hold_metrics,
                        "excess_total_return": round(
                            rl_metrics["total_return"] - buy_hold_metrics["total_return"],
                            10,
                        ),
                    }
                )
            runs.append(_run_summary(episodes, seed, window_results))

    return {
        "report": "rl_stability",
        "validation": {
            "mode": "rolling_walk_forward",
            "train_years": train_years,
            "test_years": test_years,
            "look_ahead_bias_control": (
                "Every seed and episode setting trains only on each train window "
                "and evaluates on held-out test rows."
            ),
        },
        "seeds": seeds,
        "episode_counts": episode_counts,
        "reward": {
            "trade_penalty": trade_penalty,
            "drawdown_penalty": drawdown_penalty,
        },
        "runs": runs,
        "summary_by_episodes": _summary_by_episodes(runs),
        "warnings": _warnings(runs),
    }


def render_rl_stability_html(report: dict[str, object]) -> str:
    rows = []
    for episode, summary in report["summary_by_episodes"].items():
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(episode))}</td>"
            f"<td>{summary['mean_total_return']:.4f}</td>"
            f"<td>{summary['std_total_return']:.4f}</td>"
            f"<td>{summary['mean_sharpe_ratio']:.4f}</td>"
            f"<td>{summary['mean_max_drawdown']:.4f}</td>"
            f"<td>{summary['mean_trade_count']:.1f}</td>"
            f"<td>{summary['win_rate_vs_buy_hold']:.2f}</td>"
            "</tr>"
        )
    warning_items = "".join(f"<li>{html.escape(item)}</li>" for item in report["warnings"])
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>RL Stability Report</title>"
        "<style>body{font-family:Arial,sans-serif;margin:24px;}"
        "table{border-collapse:collapse;width:100%;}td,th{border:1px solid #ccc;padding:6px;}"
        "th{background:#f3f4f6;text-align:left;}</style></head><body>"
        "<h1>RL Stability Report</h1>"
        "<table><thead><tr><th>Episodes</th><th>Mean Return</th><th>Std Return</th>"
        "<th>Mean Sharpe</th><th>Mean Max Drawdown</th><th>Mean Trades</th>"
        "<th>Win Rate vs Buy/Hold</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        f"<h2>Warnings</h2><ul>{warning_items}</ul>"
        "</body></html>"
    )


def _run_summary(
    episodes: int,
    seed: int,
    window_results: list[dict[str, object]],
) -> dict[str, object]:
    returns = [item["rl_metrics"]["total_return"] for item in window_results]
    sharpes = [item["rl_metrics"]["sharpe_ratio"] for item in window_results]
    drawdowns = [item["rl_metrics"]["max_drawdown"] for item in window_results]
    trades = [item["rl_metrics"]["trade_count"] for item in window_results]
    wins = [item["excess_total_return"] > 0 for item in window_results]
    return {
        "episodes": episodes,
        "seed": seed,
        "window_count": len(window_results),
        "mean_total_return": _mean(returns),
        "mean_sharpe_ratio": _mean(sharpes),
        "mean_max_drawdown": _mean(drawdowns),
        "mean_trade_count": _mean(trades),
        "win_rate_vs_buy_hold": _mean([1.0 if win else 0.0 for win in wins]),
        "windows": window_results,
    }


def _summary_by_episodes(runs: list[dict[str, object]]) -> dict[str, dict[str, float]]:
    grouped: dict[int, list[dict[str, object]]] = {}
    for run in runs:
        grouped.setdefault(int(run["episodes"]), []).append(run)
    return {
        str(episodes): {
            "mean_total_return": _mean([run["mean_total_return"] for run in items]),
            "std_total_return": _std([run["mean_total_return"] for run in items]),
            "mean_sharpe_ratio": _mean([run["mean_sharpe_ratio"] for run in items]),
            "mean_max_drawdown": _mean([run["mean_max_drawdown"] for run in items]),
            "mean_trade_count": _mean([run["mean_trade_count"] for run in items]),
            "win_rate_vs_buy_hold": _mean([run["win_rate_vs_buy_hold"] for run in items]),
        }
        for episodes, items in sorted(grouped.items())
    }


def _warnings(runs: list[dict[str, object]]) -> list[str]:
    warnings = []
    if any(run["mean_trade_count"] > 500 for run in runs):
        warnings.append("RL policy is trading frequently; consider stronger trade penalties.")
    if any(run["mean_max_drawdown"] < -0.2 for run in runs):
        warnings.append("Some runs exceed 20% average max drawdown; review drawdown penalty.")
    return warnings


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(float(sum(values) / len(values)), 10)


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return round(float(variance**0.5), 10)
