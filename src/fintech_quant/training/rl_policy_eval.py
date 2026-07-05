from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from fintech_quant.training.rl_dataset import RlStateSample, group_rl_state_samples_by_symbol
from fintech_quant.training.rl_environment import AShareBuySellHoldEnvironment


SUPPORTED_RL_POLICIES = ("always_hold", "buy_and_hold")


def evaluate_rl_policy(
    samples: Sequence[RlStateSample],
    *,
    policy: str,
    run_id: str = "rl-policy-evaluation",
    symbol: str | None = None,
    transaction_cost: float = 0.0,
) -> dict[str, object]:
    if policy not in SUPPORTED_RL_POLICIES:
        raise ValueError(f"policy must be one of {SUPPORTED_RL_POLICIES}")
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
        env.reset()
        if not equity_curve or equity_curve[-1]["trade_date"] != episode[0].trade_date.isoformat():
            equity_curve.append({"trade_date": episode[0].trade_date.isoformat(), "equity": round(equity, 6)})
        bought = False
        done = False
        while not done:
            action = _policy_action(policy, bought)
            previous_position = env.position
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
            bought = bought or action == "buy"
            equity_curve.append({"trade_date": step.info["next_trade_date"], "equity": round(equity, 6)})
    total_return = round(equity - 1.0, 6)
    return {
        "run_id": run_id,
        "strategy_config": {
            "policy": policy,
            "symbol": selected_symbol,
            "transaction_cost": transaction_cost,
        },
        "equity_curve": equity_curve,
        "trades": trades,
        "summary": {
            "initial_equity": 1.0,
            "ending_equity": round(equity, 6),
            "total_return": total_return,
            "trade_count": len(trades),
            "win_rate": round(positive_rewards / reward_count, 6) if reward_count else 0.0,
            "win_rate_basis": "positive_reward_steps",
            "win_rate_sample_count": reward_count,
        },
    }


def write_rl_policy_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _policy_action(policy: str, bought: bool) -> str:
    if policy == "always_hold":
        return "hold"
    if policy == "buy_and_hold":
        return "hold" if bought else "buy"
    raise ValueError(f"policy must be one of {SUPPORTED_RL_POLICIES}")
