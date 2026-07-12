from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from enum import Enum
from typing import Mapping


class DrawdownRegime(str, Enum):
    NORMAL = "normal"
    REDUCED = "reduced"
    LIQUIDATED = "liquidated"


@dataclass(frozen=True)
class DrawdownControlPolicy:
    reduce_at: float = 0.08
    liquidate_at: float = 0.10
    recover_to_reduced_at: float = 0.08
    recover_to_normal_at: float = 0.06

    def __post_init__(self) -> None:
        if not 0 < self.recover_to_normal_at < self.recover_to_reduced_at:
            raise ValueError("recovery thresholds must satisfy 0 < normal < reduced")
        if self.recover_to_reduced_at > self.reduce_at:
            raise ValueError("recover_to_reduced_at must not exceed reduce_at")
        if not self.reduce_at < self.liquidate_at < 1:
            raise ValueError("drawdown thresholds must satisfy reduce_at < liquidate_at < 1")


@dataclass(frozen=True)
class DrawdownTransition:
    trade_date: date
    from_regime: DrawdownRegime
    to_regime: DrawdownRegime
    actual_drawdown: float
    shadow_drawdown: float


@dataclass(frozen=True)
class DrawdownControlState:
    regime: DrawdownRegime
    actual_peak: float
    shadow_peak: float
    transitions: tuple[DrawdownTransition, ...] = ()
    last_transition_date: date | None = None

    @classmethod
    def initial(cls, equity: float) -> DrawdownControlState:
        if equity <= 0:
            raise ValueError("initial drawdown-control equity must be positive")
        return cls(DrawdownRegime.NORMAL, float(equity), float(equity))


@dataclass(frozen=True)
class DrawdownControlDecision:
    state: DrawdownControlState
    actual_drawdown: float
    shadow_drawdown: float
    exposure_multiplier: float


def standard_drawdown_control_policy() -> DrawdownControlPolicy:
    return DrawdownControlPolicy(
        reduce_at=0.08,
        liquidate_at=0.09,
        recover_to_reduced_at=0.08,
        recover_to_normal_at=0.06,
    )


def drawdown_exposure_multiplier(
    regime_or_state: DrawdownRegime | DrawdownControlState,
) -> float:
    regime = (
        regime_or_state.regime
        if isinstance(regime_or_state, DrawdownControlState)
        else regime_or_state
    )
    return {
        DrawdownRegime.NORMAL: 1.0,
        DrawdownRegime.REDUCED: 0.5,
        DrawdownRegime.LIQUIDATED: 0.0,
    }[regime]


def update_drawdown_control(
    state: DrawdownControlState,
    *,
    trade_date: date,
    actual_equity: float,
    shadow_equity: float,
    policy: DrawdownControlPolicy | None = None,
) -> DrawdownControlDecision:
    if actual_equity <= 0 or shadow_equity <= 0:
        raise ValueError("drawdown-control equity must be positive")
    active_policy = policy or DrawdownControlPolicy()
    actual_peak = max(state.actual_peak, actual_equity)
    shadow_peak = max(state.shadow_peak, shadow_equity)
    actual_drawdown = _drawdown(actual_equity, actual_peak)
    shadow_drawdown = _drawdown(shadow_equity, shadow_peak)
    next_regime = state.regime
    reset_actual_peak = False

    if state.regime is DrawdownRegime.NORMAL:
        if actual_drawdown >= active_policy.liquidate_at:
            next_regime = DrawdownRegime.LIQUIDATED
        elif actual_drawdown >= active_policy.reduce_at:
            next_regime = DrawdownRegime.REDUCED
    elif state.regime is DrawdownRegime.REDUCED:
        if actual_drawdown >= active_policy.liquidate_at:
            next_regime = DrawdownRegime.LIQUIDATED
        elif (
            shadow_drawdown <= active_policy.recover_to_normal_at
            and state.last_transition_date != trade_date
        ):
            next_regime = DrawdownRegime.NORMAL
    elif (
        shadow_drawdown <= active_policy.recover_to_reduced_at
        and state.last_transition_date != trade_date
    ):
        next_regime = DrawdownRegime.REDUCED
        reset_actual_peak = True

    next_state = replace(state, actual_peak=actual_peak, shadow_peak=shadow_peak)
    if next_regime is not state.regime:
        transition = DrawdownTransition(
            trade_date=trade_date,
            from_regime=state.regime,
            to_regime=next_regime,
            actual_drawdown=round(actual_drawdown, 8),
            shadow_drawdown=round(shadow_drawdown, 8),
        )
        next_state = replace(
            next_state,
            regime=next_regime,
            actual_peak=float(actual_equity) if reset_actual_peak else actual_peak,
            transitions=(*state.transitions, transition),
            last_transition_date=trade_date,
        )
    return DrawdownControlDecision(
        state=next_state,
        actual_drawdown=round(actual_drawdown, 8),
        shadow_drawdown=round(shadow_drawdown, 8),
        exposure_multiplier=drawdown_exposure_multiplier(next_state),
    )


def _drawdown(equity: float, peak: float) -> float:
    return round(max(0.0, (peak - equity) / peak), 12) if peak > 0 else 0.0


def drawdown_control_state_to_json(state: DrawdownControlState) -> dict[str, object]:
    return {
        "regime": state.regime.value,
        "actual_peak": state.actual_peak,
        "shadow_peak": state.shadow_peak,
        "last_transition_date": (
            state.last_transition_date.isoformat() if state.last_transition_date else None
        ),
        "transitions": [
            {
                "trade_date": transition.trade_date.isoformat(),
                "from_regime": transition.from_regime.value,
                "to_regime": transition.to_regime.value,
                "actual_drawdown": transition.actual_drawdown,
                "shadow_drawdown": transition.shadow_drawdown,
            }
            for transition in state.transitions
        ],
    }


def drawdown_control_state_from_json(
    payload: Mapping[str, object],
) -> DrawdownControlState:
    raw_transitions = payload.get("transitions", [])
    if not isinstance(raw_transitions, list):
        raise ValueError("drawdown-control transitions must be a list")
    transitions = tuple(
        DrawdownTransition(
            trade_date=date.fromisoformat(str(item["trade_date"])),
            from_regime=DrawdownRegime(str(item["from_regime"])),
            to_regime=DrawdownRegime(str(item["to_regime"])),
            actual_drawdown=float(item["actual_drawdown"]),
            shadow_drawdown=float(item["shadow_drawdown"]),
        )
        for item in raw_transitions
        if isinstance(item, Mapping)
    )
    raw_last_date = payload.get("last_transition_date")
    return DrawdownControlState(
        regime=DrawdownRegime(str(payload["regime"])),
        actual_peak=float(payload["actual_peak"]),
        shadow_peak=float(payload["shadow_peak"]),
        transitions=transitions,
        last_transition_date=(date.fromisoformat(str(raw_last_date)) if raw_last_date else None),
    )
