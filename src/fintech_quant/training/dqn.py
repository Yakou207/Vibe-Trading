from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from random import Random
from typing import Deque, Mapping, NamedTuple

import pandas as pd
import torch
from torch import nn

from fintech_quant.features.indicators import feature_columns as default_feature_columns
from fintech_quant.strategies.base import Strategy
from fintech_quant.trading import TradeAction, TradeDecision
from fintech_quant.training.q_learning import training_reward


ACTIONS = (TradeAction.HOLD, TradeAction.BUY, TradeAction.SELL)


@dataclass(frozen=True)
class DQNConfig:
    episodes: int = 5
    gamma: float = 0.95
    learning_rate: float = 0.001
    epsilon: float = 0.2
    min_epsilon: float = 0.05
    epsilon_decay: float = 0.95
    batch_size: int = 64
    replay_capacity: int = 10_000
    target_update_interval: int = 100
    trade_penalty: float = 0.0005
    drawdown_penalty: float = 0.0
    hidden_layers: tuple[int, ...] = (64, 32)
    seed: int = 42

    def exploration_rate(self, episode: int) -> float:
        return max(self.min_epsilon, self.epsilon * (self.epsilon_decay**episode))


@dataclass(frozen=True)
class FeatureScaler:
    columns: tuple[str, ...]
    means: dict[str, float]
    stds: dict[str, float]

    @classmethod
    def fit(cls, frame: pd.DataFrame, columns: list[str] | None = None) -> FeatureScaler:
        selected = columns or [column for column in default_feature_columns() if column in frame.columns]
        if not selected:
            selected = ["close"]
        means: dict[str, float] = {}
        stds: dict[str, float] = {}
        for column in selected:
            series = pd.to_numeric(frame[column], errors="coerce")
            mean = float(series.mean()) if not series.dropna().empty else 0.0
            std = float(series.std()) if not series.dropna().empty else 1.0
            means[column] = 0.0 if pd.isna(mean) else mean
            stds[column] = 1.0 if pd.isna(std) or std == 0 else std
        return cls(columns=tuple(selected), means=means, stds=stds)

    def transform_row(self, row: Mapping[str, object], position_flag: int) -> list[float]:
        values = []
        for column in self.columns:
            values.append((_float(row.get(column), self.means[column]) - self.means[column]) / self.stds[column])
        values.append(float(position_flag))
        return values


class Transition(NamedTuple):
    state: list[float]
    action_index: int
    reward: float
    next_state: list[float]
    done: bool


class DQNNetwork(nn.Module):
    def __init__(self, input_size: int, hidden_layers: tuple[int, ...], output_size: int) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        current_size = input_size
        for hidden_size in hidden_layers:
            layers.append(nn.Linear(current_size, hidden_size))
            layers.append(nn.ReLU())
            current_size = hidden_size
        layers.append(nn.Linear(current_size, output_size))
        self.network = nn.Sequential(*layers)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.network(inputs)


@dataclass
class DQNModel:
    network: DQNNetwork
    scaler: FeatureScaler
    config: DQNConfig
    training_steps: int
    scaler_fit_rows: int

    def q_values(self, row: Mapping[str, object], position_flag: int) -> list[float]:
        self.network.eval()
        state = torch.tensor(
            [self.scaler.transform_row(row, position_flag)],
            dtype=torch.float32,
        )
        with torch.no_grad():
            values = self.network(state).squeeze(0).tolist()
        return [float(value) for value in values]

    def best_action(self, row: Mapping[str, object], position_flag: int) -> TradeAction:
        values = self.q_values(row, position_flag)
        best_index = max(range(len(ACTIONS)), key=lambda index: (values[index], -index))
        return ACTIONS[best_index]

    def diagnostics(self) -> dict[str, object]:
        return {
            "config": asdict(self.config),
            "feature_columns": list(self.scaler.columns),
            "training_steps": self.training_steps,
            "scaler_fit_rows": self.scaler_fit_rows,
        }


@dataclass
class DQNTrainingRun:
    model: DQNModel
    target_network: DQNNetwork
    optimizer_state: dict[str, object]
    replay: Deque[Transition]
    episodes_trained: int
    metadata: dict[str, object] = field(default_factory=dict)
    metrics: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DQNStrategy(Strategy):
    model: DQNModel
    name: str = "dqn_v1"
    target_weight: float = 0.1

    def decide(self, state: dict[str, object]) -> TradeDecision:
        position_flag = 1 if int(state.get("position_quantity", 0)) > 0 else 0
        action = self.model.best_action(state, position_flag)
        confidence = self.target_weight if action is TradeAction.BUY else 1.0
        return TradeDecision(action=action, confidence=confidence, reason="DQN policy.")


def train_dqn(frame: pd.DataFrame, config: DQNConfig | None = None) -> DQNModel:
    return train_dqn_run(frame, config).model


def train_dqn_run(
    frame: pd.DataFrame,
    config: DQNConfig | None = None,
    initial_run: DQNTrainingRun | None = None,
) -> DQNTrainingRun:
    config = config or DQNConfig()
    if frame.empty:
        raise ValueError("DQN training frame must not be empty.")
    training = _training_frame(frame)
    if len(training) < 2:
        raise ValueError("DQN training frame must contain at least two usable rows.")

    torch.manual_seed(config.seed)
    rng = Random(config.seed)
    if initial_run is None:
        scaler = FeatureScaler.fit(training)
        network = DQNNetwork(
            input_size=len(scaler.columns) + 1,
            hidden_layers=config.hidden_layers,
            output_size=len(ACTIONS),
        )
        target_network = DQNNetwork(
            input_size=len(scaler.columns) + 1,
            hidden_layers=config.hidden_layers,
            output_size=len(ACTIONS),
        )
        target_network.load_state_dict(network.state_dict())
        replay: Deque[Transition] = deque(maxlen=config.replay_capacity)
        training_steps = 0
        episodes_trained = 0
    else:
        scaler = initial_run.model.scaler
        network = initial_run.model.network
        target_network = initial_run.target_network
        replay = deque(initial_run.replay, maxlen=config.replay_capacity)
        training_steps = initial_run.model.training_steps
        episodes_trained = initial_run.episodes_trained

    optimizer = torch.optim.Adam(network.parameters(), lr=config.learning_rate)
    if initial_run is not None:
        optimizer.load_state_dict(initial_run.optimizer_state)
    loss_fn = nn.MSELoss()

    grouped = _training_groups(training)
    for episode in range(config.episodes):
        epsilon = config.exploration_rate(episodes_trained + episode)
        for _symbol, rows in grouped:
            position_flag = 0
            equity = 1.0
            peak_equity = 1.0
            for index, row in enumerate(rows[:-1]):
                next_row = rows[index + 1]
                state = scaler.transform_row(row, position_flag)
                action_index = _choose_action_index(network, state, epsilon, rng)
                action = ACTIONS[action_index]
                next_position_flag = _next_position(position_flag, action)
                next_return = _float(row.get("target_next_return_1d"), 0.0)
                next_equity = equity * (1 + next_position_flag * next_return)
                peak_equity = max(peak_equity, next_equity)
                drawdown = 0.0 if peak_equity == 0 else max(0.0, 1 - next_equity / peak_equity)
                reward = training_reward(
                    action=action,
                    position_flag=position_flag,
                    next_position_flag=next_position_flag,
                    next_return=next_return,
                    trade_penalty=config.trade_penalty,
                    drawdown=drawdown,
                    drawdown_penalty=config.drawdown_penalty,
                )
                replay.append(
                    Transition(
                        state=state,
                        action_index=action_index,
                        reward=reward,
                        next_state=scaler.transform_row(next_row, next_position_flag),
                        done=index == len(rows) - 2,
                    )
                )
                if len(replay) >= config.batch_size:
                    _train_batch(
                        network=network,
                        target_network=target_network,
                        optimizer=optimizer,
                        loss_fn=loss_fn,
                        replay=replay,
                        batch_size=config.batch_size,
                        gamma=config.gamma,
                        rng=rng,
                    )
                    training_steps += 1
                    if training_steps % config.target_update_interval == 0:
                        target_network.load_state_dict(network.state_dict())
                position_flag = next_position_flag
                equity = next_equity

    target_network.load_state_dict(network.state_dict())
    model = DQNModel(
        network=network,
        scaler=scaler,
        config=config,
        training_steps=training_steps,
        scaler_fit_rows=len(frame),
    )
    return DQNTrainingRun(
        model=model,
        target_network=target_network,
        optimizer_state=optimizer.state_dict(),
        replay=replay,
        episodes_trained=episodes_trained + config.episodes,
    )


def _training_frame(frame: pd.DataFrame) -> pd.DataFrame:
    training = frame.copy()
    training["date"] = pd.to_datetime(training["date"]).dt.date.astype(str)
    training = training.sort_values(["代码", "date"]).reset_index(drop=True)
    # Recompute labels inside the supplied in-sample frame so the final train row
    # for each symbol cannot inherit an out-of-sample next-day return.
    groups = training.groupby("代码", group_keys=False)
    training["target_next_return_1d"] = groups["close"].pct_change().groupby(training["代码"]).shift(-1)
    return training.dropna(subset=["target_next_return_1d"]).reset_index(drop=True)


def _training_groups(frame: pd.DataFrame) -> list[tuple[str, list[dict[str, object]]]]:
    return [
        (str(symbol), group.to_dict("records"))
        for symbol, group in frame.groupby("代码", sort=True)
        if len(group) >= 2
    ]


def _choose_action_index(
    network: DQNNetwork,
    state: list[float],
    epsilon: float,
    rng: Random,
) -> int:
    if rng.random() < epsilon:
        return rng.randrange(len(ACTIONS))
    network.eval()
    with torch.no_grad():
        values = network(torch.tensor([state], dtype=torch.float32)).squeeze(0)
    return int(torch.argmax(values).item())


def _train_batch(
    network: DQNNetwork,
    target_network: DQNNetwork,
    optimizer: torch.optim.Optimizer,
    loss_fn: nn.Module,
    replay: Deque[Transition],
    batch_size: int,
    gamma: float,
    rng: Random,
) -> None:
    batch = rng.sample(list(replay), batch_size)
    states = torch.tensor([transition.state for transition in batch], dtype=torch.float32)
    actions = torch.tensor(
        [[transition.action_index] for transition in batch],
        dtype=torch.int64,
    )
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


def _next_position(position_flag: int, action: TradeAction) -> int:
    if action is TradeAction.BUY:
        return 1
    if action is TradeAction.SELL:
        return 0
    return position_flag


def _float(value: object, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if pd.isna(number):
        return default
    return number
