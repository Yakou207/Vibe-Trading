from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from random import Random
from typing import Any, Deque, NamedTuple, Sequence

from fintech_quant.training.dqn import DQN_ACTIONS
from fintech_quant.training.policy_report import SymbolPolicyEvaluation, build_policy_report, selected_symbols
from fintech_quant.training.rl_dataset import RlStateSample, group_rl_state_samples_by_symbol
from fintech_quant.training.rl_environment import AShareBuySellHoldEnvironment


TORCH_DQN_POLICY_NAME = "torch_dqn_v1"


@dataclass(frozen=True)
class TorchDQNConfig:
    episodes: int = 5
    gamma: float = 0.95
    learning_rate: float = 0.001
    epsilon: float = 0.2
    min_epsilon: float = 0.05
    epsilon_decay: float = 0.95
    batch_size: int = 64
    replay_capacity: int = 10_000
    target_update_interval: int = 100
    transaction_cost: float = 0.0
    drawdown_penalty: float = 0.0
    hidden_layers: tuple[int, ...] = (64, 32)
    seed: int = 42

    def exploration_rate(self, episode: int) -> float:
        return max(self.min_epsilon, self.epsilon * (self.epsilon_decay**episode))


@dataclass(frozen=True)
class FeatureScaler:
    means: tuple[float, ...]
    stds: tuple[float, ...]

    @classmethod
    def fit(cls, samples: Sequence[RlStateSample]) -> FeatureScaler:
        if not samples:
            raise ValueError("samples must not be empty")
        width = len(samples[0].state_vector)
        columns = [[sample.state_vector[index] for sample in samples] for index in range(width)]
        means = tuple(sum(values) / len(values) for values in columns)
        stds = tuple(_std_or_one(values, mean) for values, mean in zip(columns, means, strict=True))
        return cls(means=means, stds=stds)

    def transform(self, values: Sequence[float], position: int) -> list[float]:
        scaled = [
            (float(value) - mean) / std
            for value, mean, std in zip(values, self.means, self.stds, strict=True)
        ]
        scaled.append(float(position))
        return scaled


class Transition(NamedTuple):
    state: list[float]
    action_index: int
    reward: float
    next_state: list[float]
    done: bool


@dataclass
class TorchDQNPolicy:
    network: Any
    scaler: FeatureScaler
    state_fields: tuple[str, ...]
    config: TorchDQNConfig
    training_steps: int

    @property
    def observation_fields(self) -> tuple[str, ...]:
        return self.state_fields + ("position",)

    def action(self, observation: Sequence[float]) -> str:
        position = int(float(observation[-1])) if observation else 0
        state_values = observation[: len(self.state_fields)]
        state = self.scaler.transform(state_values, position)
        torch = _load_torch()
        self.network.eval()
        with torch.no_grad():
            values = self.network(torch.tensor([state], dtype=torch.float32)).squeeze(0).tolist()
        return DQN_ACTIONS[max(range(len(DQN_ACTIONS)), key=lambda index: (values[index], -index))]

    def diagnostics(self) -> dict[str, object]:
        return {
            "type": TORCH_DQN_POLICY_NAME,
            "config": asdict(self.config),
            "observation_fields": list(self.observation_fields),
            "actions": list(DQN_ACTIONS),
            "training_steps": self.training_steps,
        }


@dataclass
class TorchDQNTrainingRun:
    policy: TorchDQNPolicy
    target_network: Any
    optimizer_state: dict[str, object]
    replay: Deque[Transition]
    episodes_trained: int
    metadata: dict[str, object] = field(default_factory=dict)
    metrics: dict[str, object] = field(default_factory=dict)


def train_torch_dqn_policy(
    samples: Sequence[RlStateSample],
    config: TorchDQNConfig | None = None,
) -> TorchDQNPolicy:
    return train_torch_dqn_policy_run(samples, config).policy


def train_torch_dqn_policy_run(
    samples: Sequence[RlStateSample],
    config: TorchDQNConfig | None = None,
    initial_run: TorchDQNTrainingRun | None = None,
) -> TorchDQNTrainingRun:
    torch = _load_torch()
    nn = torch.nn
    config = config or TorchDQNConfig()
    _validate_config(config)
    if not samples:
        raise ValueError("samples must not be empty")

    episodes_by_symbol = group_rl_state_samples_by_symbol(samples)
    first_episode = next(iter(episodes_by_symbol.values()))[0]
    first_sample = first_episode[0]
    rng = Random(config.seed)
    torch.manual_seed(config.seed)
    if initial_run is None:
        scaler = FeatureScaler.fit(samples)
        state_fields = first_sample.state_fields
        input_size = len(state_fields) + 1
        network = _build_network(nn, input_size, config.hidden_layers, len(DQN_ACTIONS))
        target_network = _build_network(nn, input_size, config.hidden_layers, len(DQN_ACTIONS))
        target_network.load_state_dict(network.state_dict())
        replay: Deque[Transition] = deque(maxlen=config.replay_capacity)
        training_steps = 0
        episodes_trained = 0
        metadata: dict[str, object] = {}
        metrics: dict[str, object] = {}
    else:
        scaler = initial_run.policy.scaler
        state_fields = initial_run.policy.state_fields
        if len(first_sample.state_fields) != len(state_fields):
            raise ValueError("initial DQN checkpoint state width does not match training samples")
        network = initial_run.policy.network
        target_network = initial_run.target_network
        replay = deque(initial_run.replay, maxlen=config.replay_capacity)
        training_steps = initial_run.policy.training_steps
        episodes_trained = initial_run.episodes_trained
        metadata = dict(initial_run.metadata)
        metrics = dict(initial_run.metrics)

    optimizer = torch.optim.Adam(network.parameters(), lr=config.learning_rate)
    if initial_run is not None:
        optimizer.load_state_dict(initial_run.optimizer_state)
    loss_fn = nn.MSELoss()

    for episode_index in range(config.episodes):
        epsilon = config.exploration_rate(episodes_trained + episode_index)
        for episodes in episodes_by_symbol.values():
            for episode in episodes:
                position = 0
                equity = 1.0
                peak_equity = 1.0
                for index, sample in enumerate(episode):
                    state = scaler.transform(sample.state_vector, position)
                    action_index = _choose_action_index(torch, network, state, epsilon, rng)
                    action = DQN_ACTIONS[action_index]
                    next_position = _next_position(position, action)
                    next_equity = equity * (1.0 + next_position * sample.forward_return_1d)
                    peak_equity = max(peak_equity, next_equity)
                    drawdown = 0.0 if peak_equity == 0 else max(0.0, 1.0 - next_equity / peak_equity)
                    reward = _reward(
                        next_position,
                        sample.forward_return_1d,
                        benchmark_return=sample.benchmark_return_1d,
                        changed_position=next_position != position,
                        transaction_cost=config.transaction_cost,
                        drawdown=drawdown,
                        drawdown_penalty=config.drawdown_penalty,
                    )
                    next_sample = episode[index + 1] if index + 1 < len(episode) else sample
                    replay.append(
                        Transition(
                            state=state,
                            action_index=action_index,
                            reward=reward,
                            next_state=scaler.transform(next_sample.state_vector, next_position),
                            done=sample.terminal or index == len(episode) - 1,
                        )
                    )
                    if len(replay) >= config.batch_size:
                        _train_batch(
                            torch,
                            network,
                            target_network,
                            optimizer,
                            loss_fn,
                            replay,
                            config.batch_size,
                            config.gamma,
                            rng,
                        )
                        training_steps += 1
                        if training_steps % config.target_update_interval == 0:
                            target_network.load_state_dict(network.state_dict())
                    position = next_position
                    equity = next_equity

    target_network.load_state_dict(network.state_dict())
    policy = TorchDQNPolicy(
        network=network,
        scaler=scaler,
        state_fields=state_fields,
        config=config,
        training_steps=training_steps,
    )
    metrics.update(
        {
            "episodes_trained": episodes_trained + config.episodes,
            "training_steps": training_steps,
            "replay_size": len(replay),
        }
    )
    return TorchDQNTrainingRun(
        policy=policy,
        target_network=target_network,
        optimizer_state=optimizer.state_dict(),
        replay=replay,
        episodes_trained=episodes_trained + config.episodes,
        metadata=metadata,
        metrics=metrics,
    )


def train_torch_dqn_policy_report(
    samples: Sequence[RlStateSample],
    *,
    run_id: str = "torch-dqn",
    symbol: str | None = None,
    config: TorchDQNConfig | None = None,
) -> dict[str, object]:
    policy = train_torch_dqn_policy(samples, config)
    report = evaluate_torch_dqn_policy(samples, policy, run_id=run_id, symbol=symbol)
    report["model"] = policy.diagnostics()
    return report


def evaluate_torch_dqn_policy(
    samples: Sequence[RlStateSample],
    policy: TorchDQNPolicy,
    *,
    run_id: str = "torch-dqn",
    symbol: str | None = None,
) -> dict[str, object]:
    episodes_by_symbol = group_rl_state_samples_by_symbol(samples)
    selected, report_symbol = selected_symbols(episodes_by_symbol, symbol)
    evaluations = [
        _evaluate_symbol_policy(episodes_by_symbol[selected_symbol], selected_symbol, policy)
        for selected_symbol in selected
    ]
    return build_policy_report(
        run_id=run_id,
        strategy_config={
            "policy": TORCH_DQN_POLICY_NAME,
            "symbol": report_symbol,
            "transaction_cost": policy.config.transaction_cost,
            "drawdown_penalty": policy.config.drawdown_penalty,
            "reward_basis": "benchmark_relative_excess_return",
        },
        evaluations=evaluations,
        win_rate_basis="positive_reward_steps",
    )


def write_torch_dqn_policy_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _evaluate_symbol_policy(
    episodes: Sequence[Sequence[RlStateSample]],
    selected_symbol: str,
    policy: TorchDQNPolicy,
) -> SymbolPolicyEvaluation:
    equity = 1.0
    equity_curve: list[dict[str, object]] = []
    trades: list[dict[str, object]] = []
    reward_count = 0
    positive_rewards = 0
    for episode in episodes:
        env = AShareBuySellHoldEnvironment(episode, transaction_cost=policy.config.transaction_cost)
        observation = env.reset()
        if not equity_curve or equity_curve[-1]["trade_date"] != episode[0].trade_date.isoformat():
            equity_curve.append({"trade_date": episode[0].trade_date.isoformat(), "equity": round(equity, 6)})
        done = False
        while not done:
            previous_position = env.position
            step = env.step(policy.action(observation))
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
    return SymbolPolicyEvaluation(
        symbol=selected_symbol,
        equity_curve=equity_curve,
        trades=trades,
        reward_count=reward_count,
        positive_rewards=positive_rewards,
    )


def _build_network(nn: Any, input_size: int, hidden_layers: tuple[int, ...], output_size: int) -> Any:
    layers: list[Any] = []
    current_size = input_size
    for hidden_size in hidden_layers:
        layers.append(nn.Linear(current_size, hidden_size))
        layers.append(nn.ReLU())
        current_size = hidden_size
    layers.append(nn.Linear(current_size, output_size))
    return nn.Sequential(*layers)


def _choose_action_index(torch: Any, network: Any, state: list[float], epsilon: float, rng: Random) -> int:
    if rng.random() < epsilon:
        return rng.randrange(len(DQN_ACTIONS))
    network.eval()
    with torch.no_grad():
        values = network(torch.tensor([state], dtype=torch.float32)).squeeze(0)
    return int(torch.argmax(values).item())


def _train_batch(
    torch: Any,
    network: Any,
    target_network: Any,
    optimizer: Any,
    loss_fn: Any,
    replay: Deque[Transition],
    batch_size: int,
    gamma: float,
    rng: Random,
) -> None:
    batch = rng.sample(list(replay), batch_size)
    states = torch.tensor([transition.state for transition in batch], dtype=torch.float32)
    actions = torch.tensor([[transition.action_index] for transition in batch], dtype=torch.int64)
    rewards = torch.tensor([transition.reward for transition in batch], dtype=torch.float32)
    next_states = torch.tensor([transition.next_state for transition in batch], dtype=torch.float32)
    dones = torch.tensor([transition.done for transition in batch], dtype=torch.float32)
    network.train()
    current_q = network(states).gather(1, actions).squeeze(1)
    with torch.no_grad():
        next_q = target_network(next_states).max(dim=1).values
        target_q = rewards + gamma * next_q * (1 - dones)
    loss = loss_fn(current_q, target_q)
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()


def _reward(
    next_position: int,
    forward_return: float,
    *,
    benchmark_return: float,
    changed_position: bool,
    transaction_cost: float,
    drawdown: float,
    drawdown_penalty: float,
) -> float:
    excess_return = round(forward_return - benchmark_return, 12)
    reward = next_position * excess_return
    if changed_position:
        reward -= transaction_cost
    if next_position and drawdown_penalty > 0:
        reward -= drawdown * drawdown_penalty
    return reward


def _next_position(position: int, action: str) -> int:
    if action == "buy":
        return 1
    if action == "sell":
        return 0
    return position


def _std_or_one(values: Sequence[float], mean: float) -> float:
    if len(values) < 2:
        return 1.0
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    std = variance**0.5
    return std if std > 0 else 1.0


def _validate_config(config: TorchDQNConfig) -> None:
    _require_positive_int("episodes", config.episodes)
    _require_positive_int("batch_size", config.batch_size)
    _require_positive_int("replay_capacity", config.replay_capacity)
    _require_positive_int("target_update_interval", config.target_update_interval)
    _require_positive_number("learning_rate", config.learning_rate)
    _require_unit_ratio("gamma", config.gamma)
    _require_unit_ratio("epsilon", config.epsilon)
    _require_unit_ratio("min_epsilon", config.min_epsilon)
    _require_unit_ratio("epsilon_decay", config.epsilon_decay)
    if config.transaction_cost < 0:
        raise ValueError("transaction_cost must be greater than or equal to 0")
    if config.drawdown_penalty < 0:
        raise ValueError("drawdown_penalty must be greater than or equal to 0")
    if not config.hidden_layers or any(size <= 0 for size in config.hidden_layers):
        raise ValueError("hidden_layers must contain positive sizes")


def _require_positive_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _require_positive_number(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{name} must be greater than 0")


def _require_unit_ratio(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or value > 1:
        raise ValueError(f"{name} must be between 0 and 1")


def _load_torch() -> Any:
    try:
        import torch
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PyTorch is required for torch_dqn_v1. Install the optional rl dependencies before using this backend."
        ) from exc
    return torch
