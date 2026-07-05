from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


ALL_SYMBOLS = "ALL"


@dataclass(frozen=True)
class SymbolPolicyEvaluation:
    symbol: str
    equity_curve: list[dict[str, object]]
    trades: list[dict[str, object]]
    reward_count: int
    positive_rewards: int


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
) -> dict[str, object]:
    if not evaluations:
        raise ValueError("evaluations must not be empty")
    equity_curve = _aggregate_equity_curve(evaluations)
    trades = sorted(
        [trade for evaluation in evaluations for trade in evaluation.trades],
        key=lambda trade: (str(trade["trade_date"]), str(trade["symbol"])),
    )
    reward_count = sum(evaluation.reward_count for evaluation in evaluations)
    positive_rewards = sum(evaluation.positive_rewards for evaluation in evaluations)
    ending_equity = round(float(equity_curve[-1]["equity"]), 6)
    config = dict(strategy_config)
    config["symbols"] = [evaluation.symbol for evaluation in evaluations]
    config["symbol_count"] = len(evaluations)
    return {
        "run_id": run_id,
        "strategy_config": config,
        "equity_curve": equity_curve,
        "trades": trades,
        "summary": {
            "initial_equity": 1.0,
            "ending_equity": ending_equity,
            "total_return": round(ending_equity - 1.0, 6),
            "trade_count": len(trades),
            "win_rate": round(positive_rewards / reward_count, 6) if reward_count else 0.0,
            "win_rate_basis": win_rate_basis,
            "win_rate_sample_count": reward_count,
        },
    }


def _aggregate_equity_curve(evaluations: Sequence[SymbolPolicyEvaluation]) -> list[dict[str, object]]:
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
