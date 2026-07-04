from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from fintech_quant.training.rl_dataset import RlStateSample, group_rl_state_samples_by_symbol
from fintech_quant.training.rl_environment import AShareBuySellHoldEnvironment


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
) -> LinearQPolicy:
    if not samples:
        raise ValueError("samples must not be empty")
    _require_positive_int("epochs", epochs)
    _require_positive_number("learning_rate", learning_rate)
    _require_unit_ratio("gamma", gamma)
    if transaction_cost < 0:
        raise ValueError("transaction_cost must be greater than or equal to 0")

    episodes_by_symbol = group_rl_state_samples_by_symbol(samples)
    first_episode = next(iter(episodes_by_symbol.values()))[0]
    first_sample = first_episode[0]
    weight_count = len(first_sample.state_fields) + 2
    weights = {action: tuple(0.0 for _ in range(weight_count)) for action in DQN_ACTIONS}
    for _epoch in range(epochs):
        for episodes in episodes_by_symbol.values():
            for episode in episodes:
                weights = _train_episode(weights, episode, learning_rate, gamma, transaction_cost)
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
) -> dict[str, object]:
    policy = train_linear_dqn_policy(
        samples,
        epochs=epochs,
        learning_rate=learning_rate,
        gamma=gamma,
        transaction_cost=transaction_cost,
    )
    report = evaluate_linear_dqn_policy(
        samples,
        policy,
        run_id=run_id,
        symbol=symbol,
        transaction_cost=transaction_cost,
    )
    report["strategy_config"].update(
        {
            "epochs": epochs,
            "learning_rate": learning_rate,
            "gamma": gamma,
        }
    )
    report["model"] = {
        "type": DQN_POLICY_NAME,
        "observation_fields": list(policy.observation_fields),
        "actions": list(DQN_ACTIONS),
        "weights": {action: list(values) for action, values in sorted(policy.weights.items())},
    }
    return report


def evaluate_linear_dqn_policy(
    samples: Sequence[RlStateSample],
    policy: LinearQPolicy,
    *,
    run_id: str = "linear-q-dqn",
    symbol: str | None = None,
    transaction_cost: float = 0.0,
) -> dict[str, object]:
    episodes_by_symbol = group_rl_state_samples_by_symbol(samples)
    if not episodes_by_symbol:
        raise ValueError("samples must not be empty")
    selected_symbol = symbol or sorted(episodes_by_symbol)[0]
    if selected_symbol not in episodes_by_symbol:
        raise ValueError(f"symbol {selected_symbol} is not present in samples")

    equity = 1.0
    equity_curve: list[dict[str, object]] = []
    trades: list[dict[str, object]] = []
    reward_count = 0
    positive_rewards = 0
    for episode in episodes_by_symbol[selected_symbol]:
        env = AShareBuySellHoldEnvironment(episode, transaction_cost=transaction_cost)
        observation = env.reset()
        if not equity_curve or equity_curve[-1]["trade_date"] != episode[0].trade_date.isoformat():
            equity_curve.append({"trade_date": episode[0].trade_date.isoformat(), "equity": round(equity, 6)})
        done = False
        while not done:
            previous_position = env.position
            action = policy.action(observation)
            step = env.step(action)
            done = step.done
            equity = round(equity * (1.0 + step.reward), 6)
            reward_count += 1
            if step.reward > 0:
                positive_rewards += 1
            if step.info["position"] != previous_position:
                trades.append(
                    {
                        "trade_date": step.info["trade_date"],
                        "symbol": selected_symbol,
                        "action": step.info["action"],
                        "position": step.info["position"],
                        "transaction_cost": step.info["transaction_cost"],
                        "equity": equity,
                    }
                )
            equity_curve.append({"trade_date": step.info["next_trade_date"], "equity": round(equity, 6)})
            observation = step.observation or ()
    return {
        "run_id": run_id,
        "strategy_config": {
            "policy": DQN_POLICY_NAME,
            "symbol": selected_symbol,
            "transaction_cost": transaction_cost,
        },
        "equity_curve": equity_curve,
        "trades": trades,
        "summary": {
            "initial_equity": 1.0,
            "ending_equity": round(equity, 6),
            "total_return": round(equity - 1.0, 6),
            "trade_count": len(trades),
            "win_rate": round(positive_rewards / reward_count, 6) if reward_count else 0.0,
            "win_rate_basis": "positive_reward_steps",
        },
    }


def write_dqn_policy_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _train_episode(
    weights: dict[str, tuple[float, ...]],
    episode: Sequence[RlStateSample],
    learning_rate: float,
    gamma: float,
    transaction_cost: float,
) -> dict[str, tuple[float, ...]]:
    updated = dict(weights)
    for index, sample in enumerate(episode):
        for position in (0, 1):
            observation = tuple(sample.state_vector) + (float(position),)
            features = _features(observation)
            for action in DQN_ACTIONS:
                next_position = _next_position(position, action)
                reward = next_position * sample.forward_return_1d
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
