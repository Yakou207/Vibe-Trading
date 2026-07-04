from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from fintech_quant.trading import TradeAction
from fintech_quant.training.rl_dataset import RlStateSample


@dataclass(frozen=True)
class RlEnvironmentStep:
    observation: tuple[float, ...] | None
    reward: float
    done: bool
    info: dict[str, object]


class AShareBuySellHoldEnvironment:
    """Deterministic daily buy/sell/hold environment for A-share RL research."""

    action_space = ("buy", "sell", "hold")

    def __init__(
        self,
        samples: Sequence[RlStateSample],
        *,
        transaction_cost: float = 0.0,
    ) -> None:
        if not samples:
            raise ValueError("samples must not be empty")
        if transaction_cost < 0:
            raise ValueError("transaction_cost must be greater than or equal to 0")
        self._samples = list(samples)
        symbols = {sample.symbol for sample in self._samples}
        if len(symbols) != 1:
            raise ValueError("samples must contain a single symbol")
        self._transaction_cost = transaction_cost
        self.observation_fields = tuple(self._samples[0].state_fields) + ("position",)
        self._index = 0
        self._position = 0
        self._equity = 1.0
        self._done = False

    @property
    def position(self) -> int:
        return self._position

    @property
    def equity(self) -> float:
        return self._equity

    def reset(self) -> tuple[float, ...]:
        self._index = 0
        self._position = 0
        self._equity = 1.0
        self._done = False
        return self._observation(self._samples[self._index])

    def step(self, action: str | TradeAction) -> RlEnvironmentStep:
        if self._done:
            raise RuntimeError("environment is done; call reset before stepping again")
        action_value = _action_value(action)
        previous_position = self._position
        next_position = _next_position(previous_position, action_value)
        transaction_cost = self._transaction_cost if next_position != previous_position else 0.0
        sample = self._samples[self._index]
        reward = round(next_position * sample.forward_return_1d - transaction_cost, 6)
        self._equity = round(self._equity * (1.0 + reward), 6)
        self._position = next_position
        self._index += 1
        self._done = sample.terminal or self._index >= len(self._samples)
        observation = None if self._done else self._observation(self._samples[self._index])
        return RlEnvironmentStep(
            observation=observation,
            reward=reward,
            done=self._done,
            info={
                "symbol": sample.symbol,
                "trade_date": sample.trade_date.isoformat(),
                "next_trade_date": sample.next_trade_date.isoformat(),
                "action": action_value,
                "position": self._position,
                "forward_return_1d": sample.forward_return_1d,
                "transaction_cost": transaction_cost,
                "equity": self._equity,
            },
        )

    def _observation(self, sample: RlStateSample) -> tuple[float, ...]:
        return tuple(sample.state_vector) + (float(self._position),)


def _action_value(action: str | TradeAction) -> str:
    value = action.value if isinstance(action, TradeAction) else str(action)
    if value not in AShareBuySellHoldEnvironment.action_space:
        raise ValueError(f"action must be one of {AShareBuySellHoldEnvironment.action_space}")
    return value


def _next_position(position: int, action: str) -> int:
    if action == "buy":
        return 1
    if action == "sell":
        return 0
    return position
