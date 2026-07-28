"""T+0 intraday rotation engine on a fixed base position.

Signal: z-score of close vs cumulative VWAP (see the V3 design doc). A signal
computed on bar t is executed at bar t+1's open — lookahead is excluded by
construction. Every day ends flat-to-base: the forced-rebalance window sends
whatever leg is still open back to the base share count.

T+1 legality: sells never exceed the base (yesterday's) shares. A buy-first leg
is closed by selling an equal number of *base* shares, which is legal because
those shares were held overnight.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from fintech_quant.backtesting.costs import AShareCostModel
from datetime import date


@dataclass(frozen=True)
class RotationParams:
    z_enter: float = 2.0
    z_exit: float = 0.5
    # Economic significance floor: |close/VWAP - 1| must exceed this to open a
    # leg, so statistically-extreme-but-tiny noise (z blows up when the trailing
    # std is near zero) can never trigger a trade below the ~0.275% cost wall.
    min_abs_dev: float = 0.003
    max_rounds: int = 2
    z_window: int = 12
    z_min_window: int = 6
    slippage_rate: float = 0.0005
    # Bars at or after this time only close open legs; no new entries.
    force_close_time: str = "14:50:00"


@dataclass
class RotationDayResult:
    day: str
    trades: list[dict[str, object]] = field(default_factory=list)
    enhancement_pnl: float = 0.0
    total_cost: float = 0.0
    rounds: int = 0
    end_shares_match_base: bool = True


def rotation_signal_series(
    bars: Sequence[Mapping[str, object]], params: RotationParams
) -> list[tuple[float | None, float]]:
    """Per bar ``(z, dev)`` of the VWAP deviation; z is None while the trailing
    window is short."""
    devs: list[float] = []
    series: list[tuple[float | None, float]] = []
    cum_amount = 0.0
    cum_volume = 0.0
    for bar in bars:
        close = float(bar["close"])
        volume = max(0.0, float(bar["volume"]))
        cum_amount += close * volume
        cum_volume += volume
        vwap = cum_amount / cum_volume if cum_volume > 0 else close
        dev = close / vwap - 1.0
        devs.append(dev)
        window = devs[-params.z_window :]
        if len(window) < params.z_min_window:
            series.append((None, dev))
            continue
        spread = statistics.pstdev(window)
        series.append((dev / spread if spread > 1e-9 else None, dev))
    return series


def rotation_z_scores(bars: Sequence[Mapping[str, object]], params: RotationParams) -> list[float | None]:
    """z_t of VWAP deviation per bar; None while the trailing window is short."""
    return [z for z, _ in rotation_signal_series(bars, params)]


def run_rotation_day(
    bars: Sequence[Mapping[str, object]],
    *,
    base_shares: int,
    params: RotationParams,
    cost_model: AShareCostModel | None = None,
    trade_date: date | None = None,
) -> RotationDayResult:
    """Simulate one symbol-day. Returns the enhancement PnL net of all costs."""
    if base_shares <= 0 or len(bars) < params.z_min_window + 2:
        return RotationDayResult(day=_day_of(bars))
    costs = cost_model or AShareCostModel()
    when = trade_date or date.fromisoformat(_day_of(bars))
    signals = rotation_signal_series(bars, params)

    result = RotationDayResult(day=_day_of(bars))
    open_leg: dict[str, object] | None = None  # {"side": "sold"|"bought", "shares", "cash"}
    rounds_used = 0
    # T+1: only yesterday's shares may be sold today. EVERY round consumes its
    # share count from this budget exactly once (a sold-first leg at entry, a
    # bought-first leg at its closing sell), so the budget is reserved at entry.
    sellable_budget = base_shares

    for index in range(len(bars) - 1):
        z, dev = signals[index]
        next_bar = bars[index + 1]
        forcing = str(next_bar["datetime"])[11:] >= params.force_close_time
        if open_leg is None:
            if forcing or rounds_used >= params.max_rounds or z is None:
                continue
            if sellable_budget < base_shares:
                continue
            if z >= params.z_enter and dev >= params.min_abs_dev:
                open_leg = _execute(next_bar, "sell", base_shares, costs, params, when, result)
                open_leg["side"] = "sold"
                sellable_budget -= base_shares
            elif z <= -params.z_enter and dev <= -params.min_abs_dev:
                open_leg = _execute(next_bar, "buy", base_shares, costs, params, when, result)
                open_leg["side"] = "bought"
                sellable_budget -= base_shares
            continue
        close_now = forcing or z is None or (
            z <= params.z_exit if open_leg["side"] == "sold" else z >= -params.z_exit
        )
        if close_now:
            reverse = "buy" if open_leg["side"] == "sold" else "sell"
            _execute(next_bar, reverse, int(open_leg["shares"]), costs, params, when, result)
            open_leg = None
            rounds_used += 1

    if open_leg is not None:
        # Defensive: close on the final bar if the force window never fired.
        reverse = "buy" if open_leg["side"] == "sold" else "sell"
        _execute(bars[-1], reverse, int(open_leg["shares"]), costs, params, when, result)
        open_leg = None
        rounds_used += 1

    result.rounds = rounds_used
    result.enhancement_pnl = round(
        sum(-float(t["signed_notional"]) for t in result.trades) - result.total_cost, 6
    )
    net_shares = sum(
        int(t["shares"]) * (1 if t["action"] == "buy" else -1) for t in result.trades
    )
    result.end_shares_match_base = net_shares == 0
    return result


def _execute(
    bar: Mapping[str, object],
    action: str,
    shares: int,
    costs: AShareCostModel,
    params: RotationParams,
    when: date,
    result: RotationDayResult,
) -> dict[str, object]:
    open_price = float(bar["open"])
    price = round(
        open_price * (1.0 + params.slippage_rate if action == "buy" else 1.0 - params.slippage_rate),
        6,
    )
    notional = round(price * shares, 6)
    cost = costs.buy_cost(notional, when) if action == "buy" else costs.sell_cost(notional, when)
    signed = notional if action == "buy" else -notional
    result.trades.append(
        {
            "datetime": str(bar["datetime"]),
            "action": action,
            "shares": shares,
            "price": price,
            "signed_notional": signed,
            "cost": cost.total,
        }
    )
    result.total_cost = round(result.total_cost + cost.total, 6)
    return {"shares": shares, "cash": signed}


def _day_of(bars: Sequence[Mapping[str, object]]) -> str:
    return str(bars[0]["datetime"])[:10] if bars else ""
