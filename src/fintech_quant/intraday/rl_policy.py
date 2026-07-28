"""Linear-Q policy head on top of the T+0 rotation engine (V3, RL track).

The policy chooses WHEN to act; the engine layer keeps every trade T+1-legal,
costed, and force-closed into the base position before the close. Actions:

    0 HOLD, 1 OPEN_SELL_LEG (sell base high), 2 OPEN_BUY_LEG (buy low),
    3 CLOSE_LEG

Illegal actions are masked, never punished-and-allowed: the policy cannot emit
an unbalanced or T+1-violating day by construction.

Per repo history (daily DQN: seed divergence, near-zero trading), training is
multi-seed by default and behavioural stability is a first-class output.

Reward: per-step mark-to-market change of the enhancement position (vs the
hold-only baseline) minus execution costs. Summed over a day this telescopes to
the engine's net enhancement PnL, so the training signal is exactly the
quantity the acceptance gates measure.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Mapping, Sequence

from fintech_quant.backtesting.costs import AShareCostModel
from fintech_quant.intraday.rotation import (
    RotationDayResult,
    RotationParams,
    _day_of,
    _execute,
    rotation_signal_series,
)

HOLD, OPEN_SELL, OPEN_BUY, CLOSE = 0, 1, 2, 3
ACTIONS = (HOLD, OPEN_SELL, OPEN_BUY, CLOSE)
FEATURE_COUNT = 6  # bias, clipped z, dev, bar return, time fraction, leg state


@dataclass(frozen=True)
class LinearQConfig:
    episodes: int = 30
    learning_rate: float = 0.01
    gamma: float = 0.99
    epsilon_start: float = 0.3
    epsilon_final: float = 0.02
    z_clip: float = 4.0


@dataclass
class LinearQPolicy:
    weights: list[list[float]]  # [action][feature]

    def q_values(self, features: Sequence[float]) -> list[float]:
        return [sum(w * f for w, f in zip(row, features)) for row in self.weights]

    def act(self, features: Sequence[float], legal: Sequence[int]) -> int:
        values = self.q_values(features)
        return max(legal, key=lambda a: values[a])


def day_features(
    bars: Sequence[Mapping[str, object]],
    params: RotationParams,
    *,
    z_clip: float = 4.0,
) -> list[list[float]]:
    signals = rotation_signal_series(bars, params)
    features: list[list[float]] = []
    for index, (bar, (z, dev)) in enumerate(zip(bars, signals)):
        prev_close = float(bars[index - 1]["close"]) if index else float(bar["open"])
        bar_return = float(bar["close"]) / prev_close - 1.0
        features.append(
            [
                1.0,
                max(-z_clip, min(z_clip, z)) if z is not None else 0.0,
                dev * 100.0,
                bar_return * 100.0,
                index / max(1, len(bars) - 1),
                0.0,  # leg state, filled at runtime
            ]
        )
    return features


def legal_actions(*, leg_side: int, budget_ok: bool, forcing: bool, z_ready: bool) -> list[int]:
    if leg_side != 0:
        return [HOLD, CLOSE] if not forcing else [CLOSE]
    if forcing or not budget_ok or not z_ready:
        return [HOLD]
    return [HOLD, OPEN_SELL, OPEN_BUY]


def run_policy_day(
    bars: Sequence[Mapping[str, object]],
    *,
    base_shares: int,
    policy: Callable[[Sequence[float], Sequence[int]], int],
    params: RotationParams,
    cost_model: AShareCostModel | None = None,
    on_transition: Callable[..., None] | None = None,
) -> RotationDayResult:
    """Run one symbol-day under a policy; same legality frame as the rule engine."""
    result = RotationDayResult(day=_day_of(bars))
    if base_shares <= 0 or len(bars) < params.z_min_window + 2:
        return result
    costs = cost_model or AShareCostModel()
    when = date.fromisoformat(_day_of(bars))
    features = day_features(bars, params, z_clip=4.0)
    signals = rotation_signal_series(bars, params)

    leg_side = 0  # 0 none, -1 sold, +1 bought
    leg_shares = 0
    sellable_budget = base_shares
    rounds = 0

    for index in range(len(bars) - 1):
        next_bar = bars[index + 1]
        forcing = str(next_bar["datetime"])[11:] >= params.force_close_time
        z, _ = signals[index]
        state = features[index]
        state[5] = float(leg_side)
        legal = legal_actions(
            leg_side=leg_side,
            budget_ok=sellable_budget >= base_shares and rounds < params.max_rounds,
            forcing=forcing,
            z_ready=z is not None,
        )
        action = policy(state, legal)
        if action not in legal:
            action = HOLD if HOLD in legal else legal[0]

        cost_paid = 0.0
        if action == OPEN_SELL:
            _execute(next_bar, "sell", base_shares, costs, params, when, result)
            cost_paid = float(result.trades[-1]["cost"])
            leg_side, leg_shares = -1, base_shares
            sellable_budget -= base_shares
        elif action == OPEN_BUY:
            _execute(next_bar, "buy", base_shares, costs, params, when, result)
            cost_paid = float(result.trades[-1]["cost"])
            leg_side, leg_shares = 1, base_shares
            sellable_budget -= base_shares
        elif action == CLOSE:
            _execute(next_bar, "buy" if leg_side < 0 else "sell", leg_shares, costs, params, when, result)
            cost_paid = float(result.trades[-1]["cost"])
            leg_side, leg_shares = 0, 0
            rounds += 1

        if on_transition is not None:
            # Enhancement delta over the coming bar for the position we now hold,
            # minus what execution just cost. Price move measured open->close of
            # the execution bar (the trade happened at its open).
            position = leg_side * leg_shares
            price_move = float(next_bar["close"]) - float(next_bar["open"])
            reward = position * price_move - cost_paid
            done = index + 1 == len(bars) - 1
            next_state = list(features[index + 1])
            next_state[5] = float(leg_side)
            next_legal = legal_actions(
                leg_side=leg_side,
                budget_ok=sellable_budget >= base_shares and rounds < params.max_rounds,
                forcing=str(bars[min(index + 2, len(bars) - 1)]["datetime"])[11:] >= params.force_close_time,
                z_ready=signals[index + 1][0] is not None,
            )
            on_transition(state, action, reward, next_state, next_legal, done)

    if leg_side != 0:  # final-bar defensive close, mirrors the rule engine
        _execute(bars[-1], "buy" if leg_side < 0 else "sell", leg_shares, costs, params, when, result)
        rounds += 1

    result.rounds = rounds
    result.enhancement_pnl = round(
        sum(-float(t["signed_notional"]) for t in result.trades) - result.total_cost, 6
    )
    net = sum(int(t["shares"]) * (1 if t["action"] == "buy" else -1) for t in result.trades)
    result.end_shares_match_base = net == 0
    return result


@dataclass
class LinearQTrainingRun:
    policy: LinearQPolicy
    seed: int
    episode_pnls: list[float] = field(default_factory=list)


def train_intraday_linear_q(
    symbol_days: Sequence[tuple[str, Sequence[Mapping[str, object]], int]],
    *,
    params: RotationParams,
    config: LinearQConfig | None = None,
    seed: int = 0,
) -> LinearQTrainingRun:
    """Q-learning over (symbol, day-bars, base_shares) episodes."""
    cfg = config or LinearQConfig()
    rng = random.Random(seed)
    weights = [[0.0] * FEATURE_COUNT for _ in ACTIONS]
    policy = LinearQPolicy(weights)
    run = LinearQTrainingRun(policy=policy, seed=seed)

    for episode in range(cfg.episodes):
        epsilon = cfg.epsilon_start + (cfg.epsilon_final - cfg.epsilon_start) * (
            episode / max(1, cfg.episodes - 1)
        )
        order = list(symbol_days)
        rng.shuffle(order)
        episode_pnl = 0.0

        def learner(state, action, reward, next_state, next_legal, done):
            target = reward
            if not done and next_legal:
                target += cfg.gamma * max(policy.q_values(next_state)[a] for a in next_legal)
            error = target - policy.q_values(state)[action]
            for i in range(FEATURE_COUNT):
                weights[action][i] += cfg.learning_rate * error * state[i]

        def actor(state, legal):
            if rng.random() < epsilon:
                return rng.choice(list(legal))
            return policy.act(state, legal)

        for _symbol, bars, base_shares in order:
            result = run_policy_day(
                bars,
                base_shares=base_shares,
                policy=actor,
                params=params,
                on_transition=learner,
            )
            episode_pnl += result.enhancement_pnl
        run.episode_pnls.append(round(episode_pnl, 2))
    return run
