from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Mapping, Protocol, Sequence

from fintech_quant.backtesting.drawdown_control import (
    DrawdownControlPolicy,
    DrawdownControlState,
    drawdown_control_state_to_json,
    drawdown_exposure_multiplier,
    update_drawdown_control,
)
from fintech_quant.training.rl_dataset import RlStateSample
from fintech_quant.training.rl_environment import AShareBuySellHoldEnvironment


ALL_SYMBOLS = "ALL"


@dataclass(frozen=True)
class SymbolPolicyEvaluation:
    symbol: str
    equity_curve: list[dict[str, object]]
    trades: list[dict[str, object]]
    reward_count: int
    positive_rewards: int
    action_counts: dict[str, int] = field(default_factory=dict)
    invested_steps: int = 0
    decisions: list[dict[str, object]] = field(default_factory=list)


class EvaluationPolicy(Protocol):
    def action(self, observation: Sequence[float]) -> str: ...


def evaluate_symbol_policy(
    episodes: Sequence[Sequence[RlStateSample]],
    *,
    selected_symbol: str,
    policy: EvaluationPolicy,
    transaction_cost: float,
) -> SymbolPolicyEvaluation:
    equity = 1.0
    equity_curve: list[dict[str, object]] = []
    trades: list[dict[str, object]] = []
    decisions: list[dict[str, object]] = []
    reward_count = 0
    positive_rewards = 0
    action_counts = {action: 0 for action in AShareBuySellHoldEnvironment.action_space}
    invested_steps = 0
    for episode in episodes:
        env = AShareBuySellHoldEnvironment(episode, transaction_cost=transaction_cost)
        observation = env.reset()
        if not equity_curve or equity_curve[-1]["trade_date"] != episode[0].trade_date.isoformat():
            equity_curve.append(
                {"trade_date": episode[0].trade_date.isoformat(), "equity": round(equity, 6)}
            )
        done = False
        while not done:
            previous_position = env.position
            action = policy.action(observation)
            action_counts[action] += 1
            step = env.step(action)
            done = step.done
            equity = round(equity * (1.0 + step.reward), 6)
            reward_count += 1
            if step.reward > 0:
                positive_rewards += 1
            if int(step.info["position"]) > 0:
                invested_steps += 1
            decisions.append(
                {
                    "trade_date": step.info["trade_date"],
                    "symbol": selected_symbol,
                    "action": step.info["action"],
                    "position": step.info["position"],
                    "transaction_cost": step.info["transaction_cost"],
                    "equity": equity,
                }
            )
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
            equity_curve.append(
                {"trade_date": step.info["next_trade_date"], "equity": round(equity, 6)}
            )
            observation = step.observation or ()
    return SymbolPolicyEvaluation(
        symbol=selected_symbol,
        equity_curve=equity_curve,
        trades=trades,
        reward_count=reward_count,
        positive_rewards=positive_rewards,
        action_counts=action_counts,
        invested_steps=invested_steps,
        decisions=decisions,
    )


def selected_symbols(
    episodes_by_symbol: Mapping[str, object],
    symbol: str | None,
) -> tuple[list[str], str]:
    available = sorted(episodes_by_symbol)
    if not available:
        raise ValueError("samples must not be empty")
    if symbol is None:
        return available, ALL_SYMBOLS if len(available) > 1 else available[0]
    if symbol.upper() == ALL_SYMBOLS:
        return available, ALL_SYMBOLS
    if symbol not in episodes_by_symbol:
        raise ValueError(f"symbol {symbol} is not present in samples")
    return [symbol], symbol


def build_policy_report(
    *,
    run_id: str,
    strategy_config: Mapping[str, object],
    evaluations: Sequence[SymbolPolicyEvaluation],
    win_rate_basis: str,
    drawdown_policy: DrawdownControlPolicy | None = None,
) -> dict[str, object]:
    if not evaluations:
        raise ValueError("evaluations must not be empty")
    shadow_equity_curve = _aggregate_equity_curve(evaluations)
    equity_curve = shadow_equity_curve
    drawdown_control = None
    if drawdown_policy is not None:
        equity_curve, drawdown_control = _apply_drawdown_control(
            shadow_equity_curve,
            drawdown_policy,
        )
    trades = sorted(
        [trade for evaluation in evaluations for trade in evaluation.trades],
        key=lambda trade: (str(trade["trade_date"]), str(trade["symbol"])),
    )
    decisions = sorted(
        [decision for evaluation in evaluations for decision in evaluation.decisions],
        key=lambda decision: (str(decision["trade_date"]), str(decision["symbol"])),
    )
    reward_count = sum(evaluation.reward_count for evaluation in evaluations)
    positive_rewards = sum(evaluation.positive_rewards for evaluation in evaluations)
    action_counts = {
        action: sum(evaluation.action_counts.get(action, 0) for evaluation in evaluations)
        for action in ("buy", "hold", "sell")
    }
    invested_steps = sum(evaluation.invested_steps for evaluation in evaluations)
    ending_equity = round(float(equity_curve[-1]["equity"]), 6)
    max_drawdown = _max_drawdown(equity_curve)
    config = dict(strategy_config)
    config["symbols"] = [evaluation.symbol for evaluation in evaluations]
    config["symbol_count"] = len(evaluations)
    report = {
        "run_id": run_id,
        "strategy_config": config,
        "equity_curve": equity_curve,
        "trades": trades,
        "decisions": decisions,
        "summary": {
            "initial_equity": 1.0,
            "ending_equity": ending_equity,
            "total_return": round(ending_equity - 1.0, 6),
            "max_drawdown": max_drawdown,
            "trade_count": len(trades),
            "action_counts": action_counts,
            "invested_step_rate": round(invested_steps / reward_count, 6) if reward_count else 0.0,
            "win_rate": round(positive_rewards / reward_count, 6) if reward_count else 0.0,
            "win_rate_basis": win_rate_basis,
            "win_rate_sample_count": reward_count,
            "equity_basis": (
                "portfolio_drawdown_controlled" if drawdown_policy is not None else "raw_policy"
            ),
        },
    }
    if drawdown_policy is not None:
        report["shadow_equity_curve"] = shadow_equity_curve
        report["shadow_summary"] = _equity_summary(shadow_equity_curve)
        report["drawdown_control"] = drawdown_control
    return report


def _max_drawdown(equity_curve: Sequence[Mapping[str, object]]) -> float:
    peak = 0.0
    maximum = 0.0
    for point in equity_curve:
        equity = float(point["equity"])
        peak = max(peak, equity)
        if peak > 0:
            maximum = max(maximum, (peak - equity) / peak)
    return round(maximum, 6)


def _equity_summary(equity_curve: Sequence[Mapping[str, object]]) -> dict[str, float]:
    ending_equity = round(float(equity_curve[-1]["equity"]), 6)
    return {
        "ending_equity": ending_equity,
        "total_return": round(ending_equity - float(equity_curve[0]["equity"]), 6),
        "max_drawdown": _max_drawdown(equity_curve),
    }


def _apply_drawdown_control(
    shadow_equity_curve: Sequence[Mapping[str, object]],
    policy: DrawdownControlPolicy,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    initial_equity = float(shadow_equity_curve[0]["equity"])
    state = DrawdownControlState.initial(initial_equity)
    actual_equity = initial_equity
    controlled = [
        {
            "trade_date": str(shadow_equity_curve[0]["trade_date"]),
            "equity": round(actual_equity, 6),
            "applied_drawdown_regime": state.regime.value,
            "exposure_multiplier": drawdown_exposure_multiplier(state),
        }
    ]
    previous_shadow_equity = initial_equity
    for point in shadow_equity_curve[1:]:
        shadow_equity = float(point["equity"])
        multiplier = drawdown_exposure_multiplier(state)
        shadow_return = shadow_equity / previous_shadow_equity - 1.0
        actual_equity *= 1.0 + multiplier * shadow_return
        decision = update_drawdown_control(
            state,
            trade_date=date.fromisoformat(str(point["trade_date"])),
            actual_equity=actual_equity,
            shadow_equity=shadow_equity,
            policy=policy,
        )
        controlled.append(
            {
                "trade_date": str(point["trade_date"]),
                "equity": round(actual_equity, 6),
                "applied_drawdown_regime": state.regime.value,
                "exposure_multiplier": multiplier,
                "next_drawdown_regime": decision.state.regime.value,
            }
        )
        state = decision.state
        previous_shadow_equity = shadow_equity
    payload = drawdown_control_state_to_json(state)
    payload["policy"] = {
        "reduce_at": policy.reduce_at,
        "liquidate_at": policy.liquidate_at,
        "recover_to_reduced_at": policy.recover_to_reduced_at,
        "recover_to_normal_at": policy.recover_to_normal_at,
    }
    return controlled, payload


def _aggregate_equity_curve(
    evaluations: Sequence[SymbolPolicyEvaluation],
) -> list[dict[str, object]]:
    dates = sorted(
        {
            str(point["trade_date"])
            for evaluation in evaluations
            for point in evaluation.equity_curve
        }
    )
    curves_by_date = [
        {str(point["trade_date"]): float(point["equity"]) for point in evaluation.equity_curve}
        for evaluation in evaluations
    ]
    rows: list[dict[str, object]] = []
    latest_equity = [1.0 for _evaluation in evaluations]
    for trade_date in dates:
        for index, curve_by_date in enumerate(curves_by_date):
            if trade_date in curve_by_date:
                latest_equity[index] = curve_by_date[trade_date]
        equity = sum(latest_equity) / len(latest_equity)
        rows.append({"trade_date": trade_date, "equity": round(equity, 6)})
    return rows
