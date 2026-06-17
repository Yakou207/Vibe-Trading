from __future__ import annotations

from collections import Counter
from dataclasses import asdict

import pandas as pd

from fintech_quant.backtesting.engine import BacktestConfig, run_daily_backtest
from fintech_quant.strategies.baseline import HoldStrategy
from fintech_quant.strategies.buy_and_hold import EqualWeightBuyAndHoldStrategy
from fintech_quant.strategies.rule_based import RsiMacdRuleStrategy
from fintech_quant.training.dqn import DQNConfig, DQNModel, DQNStrategy, train_dqn
from fintech_quant.training.q_learning import QLearningConfig, QLearningModel, QLearningStrategy
from fintech_quant.training.q_learning import train_q_learning
from fintech_quant.training.walk_forward import rolling_windows, slice_window
from fintech_quant.trading import TradeAction


def run_strategy_comparison_report(
    features: pd.DataFrame,
    q_config: QLearningConfig | None = None,
    dqn_config: DQNConfig | None = None,
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
    dqn_config = dqn_config or DQNConfig()
    backtest_config = BacktestConfig(
        initial_cash=initial_cash,
        max_position_weight=max_position_weight,
        max_portfolio_drawdown=max_portfolio_drawdown,
        commission_rate=commission_rate,
        stamp_tax_rate=stamp_tax_rate,
        slippage_rate=slippage_rate,
    )
    windows = rolling_windows(pd.to_datetime(features["date"]), train_years, test_years)
    payload_windows: list[dict[str, object]] = []
    for window in windows:
        train, test = slice_window(features, window)
        if train.empty or test.empty:
            continue
        model = train_q_learning(train, q_config)
        dqn_model = train_dqn(train, dqn_config)
        strategies = {
            "hold_only": HoldStrategy(),
            "equal_weight_buy_and_hold": EqualWeightBuyAndHoldStrategy(target_weight=target_weight),
            "rsi_macd_rule": RsiMacdRuleStrategy(target_weight=target_weight),
            "q_learning_v1": QLearningStrategy(model=model, target_weight=target_weight),
            "dqn_v1": DQNStrategy(model=dqn_model, target_weight=target_weight),
        }
        results = {
            name: run_daily_backtest(test, strategy, backtest_config)
            for name, strategy in strategies.items()
        }
        strategy_metrics = {name: asdict(result.metrics) for name, result in results.items()}
        baseline_return = strategy_metrics["equal_weight_buy_and_hold"]["total_return"]
        payload_windows.append(
            {
                "window_name": window.name,
                "train_start": window.train_start.isoformat(),
                "train_end": window.train_end.isoformat(),
                "test_start": window.test_start.isoformat(),
                "test_end": window.test_end.isoformat(),
                "train_rows": len(train),
                "test_rows": len(test),
                "strategies": strategy_metrics,
                "excess_returns": {
                    f"{name}_vs_equal_weight_buy_and_hold": round(
                        metrics["total_return"] - baseline_return,
                        10,
                    )
                    for name, metrics in strategy_metrics.items()
                    if name != "equal_weight_buy_and_hold"
                },
                "rl_diagnostics": q_learning_diagnostics(
                    model,
                    results["q_learning_v1"],
                    test,
                    target_weight,
                ),
                "dqn_diagnostics": dqn_diagnostics(
                    dqn_model,
                    results["dqn_v1"],
                    test,
                    target_weight,
                ),
            }
        )
    return {
        "report": "strategy_comparison_diagnostics",
        "validation": {
            "mode": "rolling_walk_forward",
            "train_years": train_years,
            "test_years": test_years,
            "look_ahead_bias_control": (
                "Q-learning is trained only on train rows; all strategies are "
                "backtested on the same held-out test rows."
            ),
        },
        "q_learning": asdict(q_config),
        "dqn": asdict(dqn_config),
        "windows": payload_windows,
    }


def q_learning_diagnostics(
    model: QLearningModel,
    backtest_result: object,
    test: pd.DataFrame,
    target_weight: float,
) -> dict[str, object]:
    action_counts = Counter(trade.action.value for trade in backtest_result.trades)
    for action in TradeAction:
        action_counts.setdefault(action.value, 0)
    return {
        "q_state_count": len({key[0] for key in model.q_table}),
        "q_entry_count": len(model.q_table),
        "trade_count": len(backtest_result.trades),
        "action_counts": dict(sorted(action_counts.items())),
        "decision_action_counts": _decision_action_counts(model, test, target_weight),
        "top_buy_states": _top_states(model, TradeAction.BUY),
        "top_sell_states": _top_states(model, TradeAction.SELL),
    }


def dqn_diagnostics(
    model: DQNModel,
    backtest_result: object,
    test: pd.DataFrame,
    target_weight: float,
) -> dict[str, object]:
    action_counts = Counter(trade.action.value for trade in backtest_result.trades)
    for action in TradeAction:
        action_counts.setdefault(action.value, 0)
    return {
        **model.diagnostics(),
        "trade_count": len(backtest_result.trades),
        "action_counts": dict(sorted(action_counts.items())),
        "decision_action_counts": _dqn_decision_action_counts(model, test, target_weight),
    }


def _top_states(model: QLearningModel, action: TradeAction, limit: int = 5) -> list[dict[str, object]]:
    values = [
        {"state": list(state), "q_value": round(value, 10)}
        for (state, candidate), value in model.q_table.items()
        if candidate is action
    ]
    return sorted(values, key=lambda item: item["q_value"], reverse=True)[:limit]


def _decision_action_counts(
    model: QLearningModel,
    test: pd.DataFrame,
    target_weight: float,
) -> dict[str, int]:
    strategy = QLearningStrategy(model=model, target_weight=target_weight)
    held_symbols: set[str] = set()
    counts: Counter[str] = Counter()
    frame = test.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date.astype(str)
    for row in frame.sort_values(["date", "代码"]).to_dict("records"):
        symbol = str(row["代码"])
        decision = strategy.decide(
            {
                **row,
                "position_quantity": 100 if symbol in held_symbols else 0,
            }
        )
        counts[decision.action.value] += 1
        if decision.action is TradeAction.BUY:
            held_symbols.add(symbol)
        elif decision.action is TradeAction.SELL:
            held_symbols.discard(symbol)
    for action in TradeAction:
        counts.setdefault(action.value, 0)
    return dict(sorted(counts.items()))


def _dqn_decision_action_counts(
    model: DQNModel,
    test: pd.DataFrame,
    target_weight: float,
) -> dict[str, int]:
    strategy = DQNStrategy(model=model, target_weight=target_weight)
    held_symbols: set[str] = set()
    counts: Counter[str] = Counter()
    frame = test.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date.astype(str)
    for row in frame.sort_values(["date", "代码"]).to_dict("records"):
        symbol = str(row["代码"])
        decision = strategy.decide(
            {
                **row,
                "position_quantity": 100 if symbol in held_symbols else 0,
            }
        )
        counts[decision.action.value] += 1
        if decision.action is TradeAction.BUY:
            held_symbols.add(symbol)
        elif decision.action is TradeAction.SELL:
            held_symbols.discard(symbol)
    for action in TradeAction:
        counts.setdefault(action.value, 0)
    return dict(sorted(counts.items()))
