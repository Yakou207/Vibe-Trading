from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from typing import Mapping

import pandas as pd

from fintech_quant.strategies.base import Strategy
from fintech_quant.trading import TradeAction, TradeDecision


State = tuple[str, str, str, str, int]
ACTIONS = (TradeAction.HOLD, TradeAction.BUY, TradeAction.SELL)


@dataclass(frozen=True)
class StateBinner:
    return_low: float
    return_high: float
    volatility_low: float
    volatility_high: float

    @classmethod
    def fit(cls, frame: pd.DataFrame) -> StateBinner:
        return cls(
            return_low=_quantile(frame.get("return_5d", pd.Series([0.0])), 1 / 3),
            return_high=_quantile(frame.get("return_5d", pd.Series([0.0])), 2 / 3),
            volatility_low=_quantile(frame.get("volatility_20", pd.Series([0.0])), 1 / 3),
            volatility_high=_quantile(frame.get("volatility_20", pd.Series([0.0])), 2 / 3),
        )

    def transform_row(self, row: Mapping[str, object], position_flag: int) -> State:
        return (
            _rsi_bin(_float(row.get("rsi_14"), 50.0)),
            _macd_bin(_float(row.get("macd_hist"), 0.0)),
            _three_way_bin(
                _float(row.get("return_5d"), 0.0),
                self.return_low,
                self.return_high,
                "return_down",
                "return_neutral",
                "return_up",
            ),
            _three_way_bin(
                _float(row.get("volatility_20"), 0.0),
                self.volatility_low,
                self.volatility_high,
                "vol_low",
                "vol_mid",
                "vol_high",
            ),
            1 if position_flag else 0,
        )


@dataclass(frozen=True)
class QLearningConfig:
    episodes: int = 25
    alpha: float = 0.1
    gamma: float = 0.95
    epsilon: float = 0.2
    min_epsilon: float = 0.05
    epsilon_decay: float = 0.95
    trade_penalty: float = 0.0005
    seed: int = 42

    def exploration_rate(self, episode: int) -> float:
        return max(self.min_epsilon, self.epsilon * (self.epsilon_decay**episode))


@dataclass(frozen=True)
class QLearningModel:
    binner: StateBinner
    q_table: dict[tuple[State, TradeAction], float] = field(default_factory=dict)

    def q_value(self, state: State, action: TradeAction) -> float:
        return self.q_table.get((state, action), 0.0)

    def best_action(self, state: State) -> TradeAction:
        return max(ACTIONS, key=lambda action: (self.q_value(state, action), -ACTIONS.index(action)))

    def has_state(self, state: State) -> bool:
        return any((state, action) in self.q_table for action in ACTIONS)


def train_q_learning(frame: pd.DataFrame, config: QLearningConfig | None = None) -> QLearningModel:
    config = config or QLearningConfig()
    if frame.empty:
        raise ValueError("Q-learning training frame must not be empty.")
    binner = StateBinner.fit(frame)
    model = QLearningModel(binner=binner)
    rng = Random(config.seed)
    grouped = _training_groups(frame)

    for episode in range(config.episodes):
        exploration_rate = config.exploration_rate(episode)
        for _symbol, symbol_rows in grouped:
            position_flag = 0
            rows = symbol_rows.to_dict("records")
            for index, row in enumerate(rows[:-1]):
                next_row = rows[index + 1]
                state = binner.transform_row(row, position_flag)
                action = _choose_action(model, state, exploration_rate, rng)
                next_position_flag = _next_position(position_flag, action)
                reward = _training_reward(
                    action=action,
                    position_flag=position_flag,
                    next_position_flag=next_position_flag,
                    next_return=_float(row.get("target_next_return_1d"), 0.0),
                    trade_penalty=config.trade_penalty,
                )
                next_state = binner.transform_row(next_row, next_position_flag)
                old_q = model.q_value(state, action)
                best_next = max(model.q_value(next_state, next_action) for next_action in ACTIONS)
                model.q_table[(state, action)] = old_q + config.alpha * (
                    reward + config.gamma * best_next - old_q
                )
                position_flag = next_position_flag
    return model


@dataclass(frozen=True)
class QLearningStrategy(Strategy):
    model: QLearningModel
    name: str = "q_learning_v1"
    target_weight: float = 0.1

    def decide(self, state: dict[str, object]) -> TradeDecision:
        position_flag = 1 if int(state.get("position_quantity", 0)) > 0 else 0
        q_state = self.model.binner.transform_row(state, position_flag)
        action = self.model.best_action(q_state)
        confidence = self.target_weight if action is TradeAction.BUY else 1.0
        return TradeDecision(action=action, confidence=confidence, reason="Q-learning table policy.")


def _training_groups(frame: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    training = frame.dropna(subset=["target_next_return_1d"]).copy()
    training["date"] = pd.to_datetime(training["date"]).dt.date.astype(str)
    training = training.sort_values(["代码", "date"])
    return [(str(symbol), group.copy()) for symbol, group in training.groupby("代码", sort=True)]


def _choose_action(
    model: QLearningModel,
    state: State,
    epsilon: float,
    rng: Random,
) -> TradeAction:
    if not model.has_state(state):
        return TradeAction.BUY if state[-1] == 0 else TradeAction.HOLD
    if rng.random() < epsilon:
        return rng.choice(ACTIONS)
    return model.best_action(state)


def _next_position(position_flag: int, action: TradeAction) -> int:
    if action is TradeAction.BUY:
        return 1
    if action is TradeAction.SELL:
        return 0
    return position_flag


def _training_reward(
    action: TradeAction,
    position_flag: int,
    next_position_flag: int,
    next_return: float,
    trade_penalty: float,
) -> float:
    exposure = next_position_flag
    penalty = trade_penalty if action is not TradeAction.HOLD and next_position_flag != position_flag else 0.0
    return exposure * next_return - penalty


def _quantile(series: pd.Series, q: float) -> float:
    cleaned = pd.to_numeric(series, errors="coerce").dropna()
    if cleaned.empty:
        return 0.0
    return float(cleaned.quantile(q))


def _float(value: object, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if pd.isna(number):
        return default
    return number


def _rsi_bin(value: float) -> str:
    if value < 35:
        return "rsi_low"
    if value > 65:
        return "rsi_high"
    return "rsi_mid"


def _macd_bin(value: float) -> str:
    if value > 0:
        return "macd_positive"
    if value < 0:
        return "macd_negative"
    return "macd_flat"


def _three_way_bin(
    value: float,
    low: float,
    high: float,
    low_label: str,
    mid_label: str,
    high_label: str,
) -> str:
    if value <= low:
        return low_label
    if value >= high:
        return high_label
    return mid_label
