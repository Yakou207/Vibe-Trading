from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

from fintech_quant.backtesting.drawdown_control import DrawdownControlPolicy
from fintech_quant.training.policy_report import build_policy_report, evaluate_symbol_policy, selected_symbols
from fintech_quant.training.rl_dataset import RlStateSample, group_rl_state_samples_by_symbol


DQN_POLICY_NAME = "linear_q_dqn_v0"
DQN_ACTIONS = ("sell", "hold", "buy")


@dataclass(frozen=True)
class LinearQPolicy:
    state_fields: tuple[str, ...]
    weights: dict[str, tuple[float, ...]]

    @property
    def observation_fields(self) -> tuple[str, ...]:
        return self.state_fields + ("position", "bias")

    def action(self, observation: Sequence[float]) -> str:
        features = _features(observation)
        return max(
            DQN_ACTIONS,
            key=lambda action: (_dot(self.weights[action], features), _action_rank(action)),
        )


def train_linear_dqn_policy(
    samples: Sequence[RlStateSample],
    *,
    epochs: int = 50,
    learning_rate: float = 0.05,
    gamma: float = 0.0,
    transaction_cost: float = 0.0,
    drawdown_penalty: float = 0.0,
) -> LinearQPolicy:
    if not samples:
        raise ValueError("samples must not be empty")
    _require_positive_int("epochs", epochs)
    _require_positive_number("learning_rate", learning_rate)
    _require_unit_ratio("gamma", gamma)
    if transaction_cost < 0:
        raise ValueError("transaction_cost must be greater than or equal to 0")
    if drawdown_penalty < 0:
        raise ValueError("drawdown_penalty must be greater than or equal to 0")

    episodes_by_symbol = group_rl_state_samples_by_symbol(samples)
    first_episode = next(iter(episodes_by_symbol.values()))[0]
    first_sample = first_episode[0]
    weight_count = len(first_sample.state_fields) + 2
    weights = {action: tuple(0.0 for _ in range(weight_count)) for action in DQN_ACTIONS}
    for _epoch in range(epochs):
        for episodes in episodes_by_symbol.values():
            for episode in episodes:
                weights = _train_episode(weights, episode, learning_rate, gamma, transaction_cost, drawdown_penalty)
    return LinearQPolicy(first_sample.state_fields, weights)


def train_linear_dqn_policy_report(
    samples: Sequence[RlStateSample],
    *,
    run_id: str = "linear-q-dqn",
    symbol: str | None = None,
    epochs: int = 50,
    learning_rate: float = 0.05,
    gamma: float = 0.0,
    transaction_cost: float = 0.0,
    drawdown_penalty: float = 0.0,
    eval_start: date | None = None,
    drawdown_policy: DrawdownControlPolicy | None = None,
) -> dict[str, object]:
    train_samples, eval_samples = _train_eval_split(samples, eval_start)
    policy = train_linear_dqn_policy(
        train_samples,
        epochs=epochs,
        learning_rate=learning_rate,
        gamma=gamma,
        transaction_cost=transaction_cost,
        drawdown_penalty=drawdown_penalty,
    )
    report = evaluate_linear_dqn_policy(
        eval_samples,
        policy,
        run_id=run_id,
        symbol=symbol,
        transaction_cost=transaction_cost,
        drawdown_policy=drawdown_policy,
    )
    report["strategy_config"].update(
        {
            "epochs": epochs,
            "learning_rate": learning_rate,
            "gamma": gamma,
            "drawdown_penalty": drawdown_penalty,
            "eval_start": eval_start.isoformat() if eval_start else None,
            "train_sample_count": len(train_samples),
            "eval_sample_count": len(eval_samples),
        }
    )
    report["model"] = {
        "type": DQN_POLICY_NAME,
        "observation_fields": list(policy.observation_fields),
        "actions": list(DQN_ACTIONS),
        "reward_config": {
            "transaction_cost": transaction_cost,
            "drawdown_penalty": drawdown_penalty,
            "reward_basis": "benchmark_relative_excess_return",
        },
        "weights": {action: list(values) for action, values in sorted(policy.weights.items())},
    }
    return report


def _train_eval_split(
    samples: Sequence[RlStateSample],
    eval_start: date | None,
) -> tuple[list[RlStateSample], list[RlStateSample]]:
    if eval_start is None:
        sample_list = list(samples)
        return sample_list, sample_list
    train_samples = [sample for sample in samples if sample.trade_date < eval_start]
    eval_samples = [sample for sample in samples if sample.trade_date >= eval_start]
    if not train_samples:
        raise ValueError("eval_start leaves no training samples")
    if not eval_samples:
        raise ValueError("eval_start leaves no evaluation samples")
    return train_samples, eval_samples


def evaluate_linear_dqn_policy(
    samples: Sequence[RlStateSample],
    policy: LinearQPolicy,
    *,
    run_id: str = "linear-q-dqn",
    symbol: str | None = None,
    transaction_cost: float = 0.0,
    drawdown_policy: DrawdownControlPolicy | None = None,
) -> dict[str, object]:
    episodes_by_symbol = group_rl_state_samples_by_symbol(samples)
    selected, report_symbol = selected_symbols(episodes_by_symbol, symbol)
    evaluations = [
        evaluate_symbol_policy(
            episodes_by_symbol[selected_symbol],
            selected_symbol=selected_symbol,
            policy=policy,
            transaction_cost=transaction_cost,
        )
        for selected_symbol in selected
    ]
    return build_policy_report(
        run_id=run_id,
        strategy_config={
            "policy": DQN_POLICY_NAME,
            "symbol": report_symbol,
            "transaction_cost": transaction_cost,
        },
        evaluations=evaluations,
        win_rate_basis="positive_reward_steps",
        drawdown_policy=drawdown_policy,
    )

def write_dqn_policy_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _train_episode(
    weights: dict[str, tuple[float, ...]],
    episode: Sequence[RlStateSample],
    learning_rate: float,
    gamma: float,
    transaction_cost: float,
    drawdown_penalty: float,
) -> dict[str, tuple[float, ...]]:
    updated = dict(weights)
    for index, sample in enumerate(episode):
        for position in (0, 1):
            observation = tuple(sample.state_vector) + (float(position),)
            features = _features(observation)
            for action in DQN_ACTIONS:
                next_position = _next_position(position, action)
                reward = _risk_adjusted_reward(
                    next_position,
                    sample.forward_return_1d,
                    sample.benchmark_return_1d,
                    drawdown_penalty,
                )
                if next_position != position:
                    reward -= transaction_cost
                target = reward
                if not sample.terminal and index + 1 < len(episode):
                    next_observation = tuple(episode[index + 1].state_vector) + (float(next_position),)
                    target += gamma * max(
                        _dot(updated[next_action], _features(next_observation))
                        for next_action in DQN_ACTIONS
                    )
                prediction = _dot(updated[action], features)
                error = target - prediction
                updated[action] = tuple(
                    weight + learning_rate * error * feature
                    for weight, feature in zip(updated[action], features, strict=True)
                )
    return updated


def _risk_adjusted_reward(
    next_position: int,
    forward_return: float,
    benchmark_return: float,
    drawdown_penalty: float,
) -> float:
    excess_return = round(forward_return - benchmark_return, 12)
    reward = next_position * excess_return
    if drawdown_penalty <= 0 or next_position == 0 or forward_return >= 0:
        return reward
    return reward - (abs(forward_return) * drawdown_penalty)


def _features(observation: Sequence[float]) -> tuple[float, ...]:
    return tuple(_scaled_feature(value) for value in observation) + (1.0,)


def _scaled_feature(value: float) -> float:
    numeric = float(value)
    return numeric / (1.0 + abs(numeric))


def _dot(weights: Sequence[float], features: Sequence[float]) -> float:
    return sum(weight * feature for weight, feature in zip(weights, features, strict=True))


def _next_position(position: int, action: str) -> int:
    if action == "buy":
        return 1
    if action == "sell":
        return 0
    return position


def _action_rank(action: str) -> int:
    return {"sell": 0, "buy": 1, "hold": 2}[action]


def _require_positive_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _require_positive_number(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{name} must be greater than 0")


def _require_unit_ratio(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or value > 1:
        raise ValueError(f"{name} must be between 0 and 1")
