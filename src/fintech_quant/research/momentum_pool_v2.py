"""Shadow paper book v2 for the momentum-setup screen: watchlist, risk sizing, exit rules, brake.

Research only. It never reads or writes the counted paper account, pipeline state or evidence
files, and v1 (``momentum_pool``) keeps running unchanged next to it.

Predeclared rules (written before any replay; do not tune them after seeing results):

1. Two tiers.
   - Watchlist: each refresh adds the day's top five screen results (names already held and names
     in the ``avoid`` state are not added). A name leaves the watchlist when it has been there 10
     sessions without triggering (its age resets to 0 whenever it is in the day's top five again
     or triggers), when its daily screen state is ``avoid``, or when it is bought. The watchlist is
     capped at 20 names; the oldest (largest age, then earliest added) are evicted first.
   - Positions: at most 8. A watchlist name in the ``trigger`` state is queued with that day's low
     as its stop and bought at the next open, with v1's skip rules: suspended, limit-up open, open
     at or below the stop. A queued entry expires if the next refresh is not the next session.
2. Risk sizing. Risk 0.75% of equity per trade: shares = 0.0075 x equity / (entry - stop), where
   equity is the previous close and entry is the slipped open fill. A single position is capped
   at 15% of equity (and at available cash). The entry is skipped when (entry - stop) / entry
   exceeds 4%.
3. Exits, evaluated in this order for positions held at least one session (T+1); the reason code
   of every exit is recorded:
   a. Hard stop at the signal-day low: an open at or below the stop sells at the open
      (``gap_below_stop``); otherwise a low at or below the stop sells at the stop (``stop``).
   b. Trailing exit at the close: below the 9 EMA (``close_below_ema9``); once the peak open
      profit has reached 2R, below the 21 EMA instead (``close_below_ema21``).
   c. Profit give-back: once the peak open profit has reached 2R, sell at the close when at least
      half of that peak open profit has been given back (``profit_giveback``).
   d. Time stop: after 15 held sessions, sell at the close if the open profit is below +1R
      (``time_stop``).
   e. Invalidation: sell at the close when the day's screen state is ``avoid`` (``invalidated``).
   R = entry - stop per share. Open profit is measured on closes; the peak includes today's close.
4. Portfolio brake, using the counted risk engine's drawdown controller
   (``update_drawdown_control``) with 8% / 10% / 8% / 6% thresholds: a close-to-peak drawdown of
   at least 8% halves the risk per trade (``reduced``); at least 10% blocks new entries
   (``liquidated`` in the controller's terms, but open positions are not force-sold). As in the
   counted engine, recovery is measured on an unrestricted shadow book that runs the same rules
   without the brake: back to ``reduced`` at a shadow drawdown of 8% or less, back to ``normal``
   at 6% or less. Without the shadow book an all-cash halted pool could never recover.
5. Costs and price basis as in v1: hfq prices, fractional units, 0.03% commission with a CNY 5
   minimum, 0.05% sell stamp duty, 0.05% slippage on every fill.

Each refresh for ``as_of`` runs, for the actual book and the unrestricted shadow book: exits,
then queued entries at the open, then the close mark. It then updates the brake from both
closes and finally the watchlist and the queue for the next open.

``exit_fill="next_open"`` is a sensitivity option for replays, not a rule change: exits 3b-3e are
decided on the close but queued and sold at the next unsuspended open (same slippage). Hard-stop
exits (3a) are intraday stop orders and are unchanged. The default is unchanged.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Mapping, Sequence

from fintech_quant.backtesting.drawdown_control import (
    DrawdownControlPolicy,
    DrawdownControlState,
    drawdown_control_state_from_json,
    drawdown_control_state_to_json,
    drawdown_exposure_multiplier,
    update_drawdown_control,
)
from fintech_quant.research.momentum_pool import (
    COMMISSION_RATE,
    EXIT_FILLS,
    INITIAL_EQUITY,
    MINIMUM_COMMISSION,
    MINIMUM_SLOT_CASH,
    SLIPPAGE_RATE,
    STAMP_DUTY_RATE,
    _commission,
    _index,
    _limit,
    _pool_row,
    _positions_value,
)
from fintech_quant.research.momentum_setup import SymbolSeries


DAILY_TOP = 5
WATCHLIST_CAP = 20
WATCHLIST_MAX_AGE = 10
MAX_POSITIONS = 8
RISK_PER_TRADE = 0.0075
MAX_WEIGHT = 0.15
MAX_STOP_DISTANCE = 0.04
TRAIL_SWITCH_R = 2.0
GIVEBACK_FRACTION = 0.5
TIME_STOP_SESSIONS = 15
TIME_STOP_MIN_R = 1.0
BRAKE_POLICY = DrawdownControlPolicy(
    reduce_at=0.08, liquidate_at=0.10, recover_to_reduced_at=0.08, recover_to_normal_at=0.06
)
EXIT_REASONS = (
    "gap_below_stop",
    "stop",
    "close_below_ema9",
    "close_below_ema21",
    "profit_giveback",
    "time_stop",
    "invalidated",
)
INTRADAY_EXITS = ("gap_below_stop", "stop")


def initial_pool_state() -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "momentum_shadow_pool_v2",
        "counts_toward_evidence": False,
        "as_of": None,
        "book": _initial_book(),
        "shadow_book": _initial_book(),
        "brake": drawdown_control_state_to_json(DrawdownControlState.initial(INITIAL_EQUITY)),
        "watchlist": [],
        "pool": [],
        "config": {
            "initial_equity": INITIAL_EQUITY,
            "daily_top": DAILY_TOP,
            "watchlist_cap": WATCHLIST_CAP,
            "watchlist_max_age": WATCHLIST_MAX_AGE,
            "max_positions": MAX_POSITIONS,
            "risk_per_trade": RISK_PER_TRADE,
            "max_weight": MAX_WEIGHT,
            "max_stop_distance": MAX_STOP_DISTANCE,
            "trail_switch_r": TRAIL_SWITCH_R,
            "giveback_fraction": GIVEBACK_FRACTION,
            "time_stop_sessions": TIME_STOP_SESSIONS,
            "time_stop_min_r": TIME_STOP_MIN_R,
            "brake": {
                "reduce_at": BRAKE_POLICY.reduce_at,
                "no_entries_at": BRAKE_POLICY.liquidate_at,
                "recover_to_reduced_at": BRAKE_POLICY.recover_to_reduced_at,
                "recover_to_normal_at": BRAKE_POLICY.recover_to_normal_at,
            },
            "commission_rate": COMMISSION_RATE,
            "minimum_commission": MINIMUM_COMMISSION,
            "stamp_duty_rate": STAMP_DUTY_RATE,
            "slippage_rate": SLIPPAGE_RATE,
            "price_basis": "hfq",
        },
    }


def _initial_book() -> dict[str, object]:
    return {
        "cash": INITIAL_EQUITY,
        "positions": {},
        "pending": [],
        "closed_trades": [],
        "skipped_entries": [],
        "nav_history": [],
    }


def step_pool(
    state: Mapping[str, object],
    *,
    as_of: str,
    series: Mapping[str, SymbolSeries],
    screen_results: Sequence[Mapping[str, object]],
    previous_session: str | None,
    exit_fill: str = "same_close",
) -> dict[str, object]:
    """``screen_results`` is the full ranked screen for ``as_of``; ``previous_session`` is the
    CSI 300 session before ``as_of``."""
    if exit_fill not in EXIT_FILLS:
        raise ValueError(f"exit_fill must be one of {EXIT_FILLS}: {exit_fill}")
    previous = state.get("as_of")
    if previous is not None and str(previous) >= as_of:
        raise ValueError(f"pool refresh {as_of} must follow {previous}")
    states = {str(row["symbol"]): row for row in screen_results}
    brake = drawdown_control_state_from_json(state["brake"])  # type: ignore[arg-type]
    multiplier = drawdown_exposure_multiplier(brake)
    book = _step_book(
        state["book"],  # type: ignore[arg-type]
        as_of,
        series,
        states,
        previous_session,
        multiplier,
        exit_fill,
    )
    shadow = _step_book(
        state["shadow_book"],  # type: ignore[arg-type]
        as_of,
        series,
        states,
        previous_session,
        1.0,
        exit_fill,
    )
    decision = update_drawdown_control(
        brake,
        trade_date=date.fromisoformat(as_of),
        actual_equity=float(book["nav_history"][-1]["equity"]),  # type: ignore[index]
        shadow_equity=float(shadow["nav_history"][-1]["equity"]),  # type: ignore[index]
        policy=BRAKE_POLICY,
    )
    book["nav_history"][-1]["brake"] = decision.state.regime.value  # type: ignore[index]
    book["nav_history"][-1]["drawdown"] = decision.actual_drawdown  # type: ignore[index]

    bought_today = {
        symbol for symbol, p in dict(book["positions"]).items() if p["entry_date"] == as_of  # type: ignore[arg-type]
    }
    watchlist = _update_watchlist(
        list(state["watchlist"]),  # type: ignore[arg-type]
        as_of=as_of,
        screen_results=screen_results,
        states=states,
        held=set(dict(book["positions"])),  # type: ignore[arg-type]
        bought_today=bought_today,
    )
    triggered = [row for row in watchlist if row["triggered_on"] == as_of]
    for target in (book, shadow):
        target["pending"] = [
            {"symbol": row["symbol"], "signal_date": as_of, "stop": row["stop"]}
            for row in triggered
            if row["symbol"] not in target["positions"]  # type: ignore[operator]
        ]
    return {
        **state,
        "as_of": as_of,
        "book": book,
        "shadow_book": shadow,
        "brake": drawdown_control_state_to_json(decision.state),
        "watchlist": watchlist,
        "pool": [_pool_row(row) for row in screen_results[:DAILY_TOP]],
    }


def _step_book(
    book: Mapping[str, object],
    as_of: str,
    series: Mapping[str, SymbolSeries],
    states: Mapping[str, Mapping[str, object]],
    previous_session: str | None,
    multiplier: float,
    exit_fill: str = "same_close",
) -> dict[str, object]:
    cash = float(book["cash"])  # type: ignore[arg-type]
    positions = {s: dict(p) for s, p in dict(book["positions"]).items()}  # type: ignore[arg-type]
    closed = list(book["closed_trades"])  # type: ignore[arg-type]
    skipped = list(book["skipped_entries"])  # type: ignore[arg-type]
    history = list(book["nav_history"])  # type: ignore[arg-type]
    equity_before = float(history[-1]["equity"]) if history else INITIAL_EQUITY

    for symbol in sorted(positions):
        position = positions[symbol]
        bar_index = _index(series, symbol, as_of)
        if bar_index is None:
            continue
        item = series[symbol]
        bar = item.bars[bar_index]
        queued = position.get("exit_pending")
        if queued is None:
            position["peak_close"] = max(float(position["peak_close"]), bar.close)
        if position["entry_date"] >= as_of:
            continue
        position["sessions_held"] = int(position["sessions_held"]) + 1
        if queued is not None:
            exit_rule = (bar.open, str(queued["reason"]))
        else:
            exit_rule = exit_decision(
                position,
                bar_open=bar.open,
                bar_low=bar.low,
                bar_close=bar.close,
                ema9=item.ema9[bar_index],
                ema21=item.ema21[bar_index],
                screen_state=str((states.get(symbol) or {}).get("state", "")),
            )
        if exit_rule is None:
            continue
        if queued is None and exit_fill == "next_open" and exit_rule[1] not in INTRADAY_EXITS:
            position["exit_pending"] = {"reason": exit_rule[1], "decided_on": as_of}
            continue
        price, reason = exit_rule
        fill = price * (1 - SLIPPAGE_RATE)
        notional = fill * float(position["shares"])
        fees = _commission(notional) + notional * STAMP_DUTY_RATE
        cash += notional - fees
        risk = float(position["entry_price"]) - float(position["stop"])
        closed.append(
            {
                "symbol": symbol,
                "entry_date": position["entry_date"],
                "entry_price": position["entry_price"],
                "stop": position["stop"],
                "exit_date": as_of,
                "exit_price": round(fill, 6),
                "reason": reason,
                "sessions_held": position["sessions_held"],
                "r_multiple": round((fill - float(position["entry_price"])) / risk, 4),
                "peak_r": round(_r(position, float(position["peak_close"])), 4),
                "return": round((notional - fees) / float(position["cost"]) - 1.0, 6),
            }
        )
        if queued is not None:
            closed[-1]["decided_on"] = queued["decided_on"]
        del positions[symbol]

    for pending in book["pending"]:  # type: ignore[union-attr]
        symbol = str(pending["symbol"])
        if symbol in positions or len(positions) >= MAX_POSITIONS:
            continue
        reason = None
        bar_index = _index(series, symbol, as_of)
        if pending["signal_date"] != previous_session:
            reason = "stale_signal"
        elif multiplier <= 0:
            reason = "brake_no_entries"
        elif bar_index is None:
            reason = "suspended"
        else:
            bar = series[symbol].bars[bar_index]
            previous_close = series[symbol].bars[bar_index - 1].close
            stop = float(pending["stop"])
            fill = bar.open * (1 + SLIPPAGE_RATE)
            if bar.open >= previous_close * (1 + _limit(symbol)) * 0.995:
                reason = "limit_up_open"
            elif bar.open <= stop:
                reason = "gapped_below_stop"
            elif (fill - stop) / fill > MAX_STOP_DISTANCE:
                reason = "stop_too_wide"
        if reason is None:
            notional, shares = size_entry(
                equity=equity_before, cash=cash, fill=fill, stop=stop, multiplier=multiplier
            )
            if notional < MINIMUM_SLOT_CASH:
                reason = "insufficient_cash"
        if reason is not None:
            skipped.append({"symbol": symbol, "date": as_of, "reason": reason})
            continue
        cost = notional + _commission(notional)
        cash -= cost
        positions[symbol] = {
            "entry_date": as_of,
            "signal_date": pending["signal_date"],
            "entry_price": round(fill, 6),
            "shares": round(shares, 8),
            "cost": round(cost, 6),
            "stop": stop,
            "weight": round(notional / equity_before, 6),
            "risk_multiplier": multiplier,
            "peak_close": bar.close,
            "sessions_held": 0,
        }

    positions_value = _positions_value(positions, series, as_of)
    equity = cash + positions_value
    history.append(
        {
            "trade_date": as_of,
            "cash": round(cash, 6),
            "positions_value": round(positions_value, 6),
            "equity": round(equity, 6),
            "exposure": round(positions_value / equity, 6) if equity > 0 else 0.0,
            "positions": len(positions),
        }
    )
    return {
        **book,
        "cash": round(cash, 6),
        "positions": positions,
        "closed_trades": closed,
        "skipped_entries": skipped,
        "nav_history": history,
    }


def size_entry(
    *, equity: float, cash: float, fill: float, stop: float, multiplier: float
) -> tuple[float, float]:
    """Returns (notional, shares): 0.75% x multiplier risk, capped at 15% weight and cash."""
    risk_shares = RISK_PER_TRADE * multiplier * equity / (fill - stop)
    notional = min(risk_shares * fill, MAX_WEIGHT * equity)
    notional = min(notional, cash - _commission(cash))
    return notional, notional / fill if notional > 0 else 0.0


def exit_decision(
    position: Mapping[str, object],
    *,
    bar_open: float,
    bar_low: float,
    bar_close: float,
    ema9: float,
    ema21: float,
    screen_state: str,
) -> tuple[float, str] | None:
    """Rules 3a-3e in order; ``position['peak_close']`` must already include today's close."""
    stop = float(position["stop"])
    if bar_open <= stop:
        return bar_open, "gap_below_stop"
    if bar_low <= stop:
        return stop, "stop"
    peak_r = _r(position, float(position["peak_close"]))
    current_r = _r(position, bar_close)
    if peak_r >= TRAIL_SWITCH_R:
        if bar_close < ema21:
            return bar_close, "close_below_ema21"
    elif bar_close < ema9:
        return bar_close, "close_below_ema9"
    if peak_r >= TRAIL_SWITCH_R and current_r <= peak_r * (1 - GIVEBACK_FRACTION):
        return bar_close, "profit_giveback"
    if int(position["sessions_held"]) >= TIME_STOP_SESSIONS and current_r < TIME_STOP_MIN_R:
        return bar_close, "time_stop"
    if screen_state == "avoid":
        return bar_close, "invalidated"
    return None


def _r(position: Mapping[str, object], price: float) -> float:
    entry = float(position["entry_price"])
    return (price - entry) / (entry - float(position["stop"]))


def _update_watchlist(
    watchlist: list[Mapping[str, object]],
    *,
    as_of: str,
    screen_results: Sequence[Mapping[str, object]],
    states: Mapping[str, Mapping[str, object]],
    held: set[str],
    bought_today: set[str],
) -> list[dict[str, object]]:
    current = {
        str(row["symbol"]): {**row, "age": int(row["age"]) + 1}
        for row in watchlist
        if row["symbol"] not in bought_today and row["symbol"] not in held
    }
    for symbol in list(current):
        if str((states.get(symbol) or {}).get("state")) == "avoid":
            del current[symbol]
    top = [
        row
        for row in screen_results[:DAILY_TOP]
        if row["state"] != "avoid" and row["symbol"] not in held
    ]
    for row in top:
        symbol = str(row["symbol"])
        entry = current.get(symbol) or {"symbol": symbol, "added": as_of}
        current[symbol] = {**entry, "age": 0}
    for symbol, entry in current.items():
        row = states.get(symbol)
        if row is None:
            continue
        entry.update(
            {
                "state": row["state"],
                "close": row.get("close"),
                "stop": row.get("stop"),
                "stop_pct": row.get("stop_pct"),
                "confluence": row.get("confluence"),
                "momentum_pct": (row.get("momentum") or {}).get("momentum_pct"),  # type: ignore[union-attr]
            }
        )
        if row["state"] == "trigger":
            entry["age"] = 0
            entry["triggered_on"] = as_of
    kept = [entry for entry in current.values() if int(entry["age"]) < WATCHLIST_MAX_AGE]
    order = {str(row["symbol"]): i for i, row in enumerate(screen_results)}
    kept.sort(key=lambda e: (-int(e["age"]), str(e["added"]), str(e["symbol"])))
    kept = kept[max(0, len(kept) - WATCHLIST_CAP) :]
    kept.sort(key=lambda e: (int(e["age"]), order.get(str(e["symbol"]), math.inf)))
    return [{"triggered_on": None, **entry} for entry in kept]


def position_status(
    position: Mapping[str, object], *, close: float, ema9: float, ema21: float
) -> dict[str, object]:
    """Display helper: R multiple and which exit rules are armed for an open position."""
    peak_r = _r(position, float(position["peak_close"]))
    current_r = _r(position, close)
    held = int(position["sessions_held"])
    trail = "ema21" if peak_r >= TRAIL_SWITCH_R else "ema9"
    return {
        "r_multiple": round(current_r, 3),
        "peak_r": round(peak_r, 3),
        "trail": trail,
        "trail_level": ema21 if trail == "ema21" else ema9,
        "giveback_armed": peak_r >= TRAIL_SWITCH_R,
        "giveback_exit_r": round(peak_r * (1 - GIVEBACK_FRACTION), 3)
        if peak_r >= TRAIL_SWITCH_R
        else None,
        "sessions_held": held,
        "time_stop_in": max(0, TIME_STOP_SESSIONS - held),
        "time_stop_active": held >= TIME_STOP_SESSIONS and current_r < TIME_STOP_MIN_R,
    }


def performance(
    nav_history: Sequence[Mapping[str, object]],
    closed_trades: Sequence[Mapping[str, object]],
    *,
    initial_equity: float = INITIAL_EQUITY,
    exclude: tuple[str, str] | None = None,
) -> dict[str, object]:
    """Comparable metrics for a v1 or v2 book. ``exclude`` drops the daily returns dated inside the
    window (compounding the rest) and every trade whose holding period overlaps it."""
    returns, exposures, previous = [], [], initial_equity
    for row in nav_history:
        equity = float(row["equity"])
        inside = exclude is not None and exclude[0] <= str(row["trade_date"]) <= exclude[1]
        if not inside:
            returns.append(equity / previous - 1.0)
            exposures.append(float(row["positions_value"]) / equity if equity > 0 else 0.0)
        previous = equity
    trades = [
        t
        for t in closed_trades
        if exclude is None
        or not (str(t["entry_date"]) <= exclude[1] and str(t["exit_date"]) >= exclude[0])
    ]
    stats = return_stats(returns)
    wins = [float(t["return"]) for t in trades if float(t["return"]) > 0]
    losses = [float(t["return"]) for t in trades if float(t["return"]) <= 0]
    reasons: dict[str, int] = {}
    for trade in trades:
        reasons[str(trade["reason"])] = reasons.get(str(trade["reason"]), 0) + 1
    return {
        **stats,
        "trades": len(trades),
        "win_rate": len(wins) / len(trades) if trades else None,
        "average_win": sum(wins) / len(wins) if wins else None,
        "average_loss": sum(losses) / len(losses) if losses else None,
        "exits_by_reason": dict(sorted(reasons.items())),
        "average_exposure": sum(exposures) / len(exposures) if exposures else None,
    }


def return_stats(returns: Sequence[float]) -> dict[str, object]:
    equity, peak, drawdown = 1.0, 1.0, 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        drawdown = max(drawdown, 1.0 - equity / peak)
    mean = sum(returns) / len(returns) if returns else 0.0
    variance = (
        sum((r - mean) ** 2 for r in returns) / (len(returns) - 1) if len(returns) > 1 else 0.0
    )
    return {
        "sessions": len(returns),
        "total_return": equity - 1.0,
        "max_drawdown": drawdown,
        "sharpe": mean / math.sqrt(variance) * math.sqrt(252) if variance > 0 else None,
    }


def pool_metrics(state: Mapping[str, object]) -> dict[str, object]:
    book = dict(state["book"])  # type: ignore[arg-type]
    history = list(book["nav_history"])
    metrics = performance(history, list(book["closed_trades"]))
    brake = dict(state["brake"])  # type: ignore[arg-type]
    return {
        **metrics,
        "equity": float(history[-1]["equity"]) if history else INITIAL_EQUITY,
        "drawdown": float(history[-1].get("drawdown", 0.0)) if history else 0.0,
        "brake": brake["regime"],
        "positions": len(dict(book["positions"])),
        "watchlist": len(list(state["watchlist"])),  # type: ignore[arg-type]
    }
