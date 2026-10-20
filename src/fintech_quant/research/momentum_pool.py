"""Shadow paper book for the top-5 momentum-setup pool.

Refreshed once per closed session, after the counted CSI 300 cycle. It never reads or writes the
counted paper account, pipeline state or evidence files.

Each refresh for ``as_of``:

1. Exits for positions bought before ``as_of`` (T+1): an open at or below the stop sells at the
   open; a low through the stop sells at the stop; otherwise a close under the 9 EMA sells at the
   close.
2. Entries for the previous refresh's triggered pool members at today's open, unless the stock
   is suspended, opens at its limit-up, or opens at or below its stop.
3. Marks NAV at the close.
4. Re-ranks the pool: the top five screen results, with triggered names queued for the next open.

Prices are hfq-adjusted so returns include dividends. Because hfq price levels are not tradable
prices, positions are return-equivalent fractional units (no board-lot rounding). Costs use the
counted policy rates (0.03% commission, CNY 5 minimum, 0.05% sell stamp duty, 0.05% slippage).

``exit_fill="next_open"`` is a sensitivity option for replays, not a rule change: a close-decided
exit is queued and sells at the next unsuspended open (same slippage) instead of the deciding
close. Stop and gap exits are intraday stop orders and are unchanged. The default is unchanged.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from fintech_quant.research.momentum_setup import SymbolSeries


POOL_SIZE = 5
INITIAL_EQUITY = 100000.0
COMMISSION_RATE = 0.0003
MINIMUM_COMMISSION = 5.0
STAMP_DUTY_RATE = 0.0005
SLIPPAGE_RATE = 0.0005
MINIMUM_SLOT_CASH = 1000.0
EXIT_FILLS = ("same_close", "next_open")


def initial_pool_state() -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "momentum_shadow_pool",
        "counts_toward_evidence": False,
        "as_of": None,
        "cash": INITIAL_EQUITY,
        "positions": {},
        "pending": [],
        "pool": [],
        "closed_trades": [],
        "skipped_entries": [],
        "nav_history": [],
        "config": {
            "pool_size": POOL_SIZE,
            "initial_equity": INITIAL_EQUITY,
            "commission_rate": COMMISSION_RATE,
            "minimum_commission": MINIMUM_COMMISSION,
            "stamp_duty_rate": STAMP_DUTY_RATE,
            "slippage_rate": SLIPPAGE_RATE,
            "exit_rule": "stop_or_close_below_ema9",
            "price_basis": "hfq",
        },
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
    """``previous_session`` is the CSI 300 session before ``as_of``; older queued entries expire."""
    if exit_fill not in EXIT_FILLS:
        raise ValueError(f"exit_fill must be one of {EXIT_FILLS}: {exit_fill}")
    previous = state.get("as_of")
    if previous is not None and str(previous) >= as_of:
        raise ValueError(f"pool refresh {as_of} must follow {previous}")
    cash = float(state["cash"])  # type: ignore[arg-type]
    positions = {s: dict(p) for s, p in dict(state["positions"]).items()}  # type: ignore[arg-type]
    closed = list(state["closed_trades"])  # type: ignore[arg-type]
    skipped = list(state["skipped_entries"])  # type: ignore[arg-type]

    for symbol in sorted(positions):
        position = positions[symbol]
        bar_index = _index(series, symbol, as_of)
        if bar_index is None or position["entry_date"] >= as_of:
            continue
        item = series[symbol]
        bar = item.bars[bar_index]
        stop = float(position["stop"])
        queued = position.get("exit_pending")
        if queued is not None:
            price, reason = bar.open, str(queued["reason"])
        elif bar.open <= stop:
            price, reason = bar.open, "gap_below_stop"
        elif bar.low <= stop:
            price, reason = stop, "stop"
        elif bar.close < item.ema9[bar_index]:
            if exit_fill == "next_open":
                position["exit_pending"] = {"reason": "close_below_ema9", "decided_on": as_of}
                continue
            price, reason = bar.close, "close_below_ema9"
        else:
            continue
        fill = price * (1 - SLIPPAGE_RATE)
        notional = fill * float(position["shares"])
        fees = _commission(notional) + notional * STAMP_DUTY_RATE
        cash += notional - fees
        closed.append(
            {
                "symbol": symbol,
                "entry_date": position["entry_date"],
                "entry_price": position["entry_price"],
                "exit_date": as_of,
                "exit_price": round(fill, 6),
                "reason": reason,
                "return": round((notional - fees) / float(position["cost"]) - 1.0, 6),
            }
        )
        if queued is not None:
            closed[-1]["decided_on"] = queued["decided_on"]
        del positions[symbol]

    equity_before = cash + _positions_value(positions, series, as_of)
    for pending in state["pending"]:  # type: ignore[union-attr]
        symbol = str(pending["symbol"])
        if symbol in positions or len(positions) >= POOL_SIZE:
            continue
        if pending["signal_date"] != previous_session:
            skipped.append({"symbol": symbol, "date": as_of, "reason": "stale_signal"})
            continue
        bar_index = _index(series, symbol, as_of)
        reason = None
        if bar_index is None:
            reason = "suspended"
        else:
            bar = series[symbol].bars[bar_index]
            previous_close = series[symbol].bars[bar_index - 1].close
            if bar.open >= previous_close * (1 + _limit(symbol)) * 0.995:
                reason = "limit_up_open"
            elif bar.open <= float(pending["stop"]):
                reason = "gapped_below_stop"
        if reason is not None:
            skipped.append({"symbol": symbol, "date": as_of, "reason": reason})
            continue
        fill = bar.open * (1 + SLIPPAGE_RATE)
        budget = min(cash, equity_before / POOL_SIZE)
        if budget < MINIMUM_SLOT_CASH:
            skipped.append({"symbol": symbol, "date": as_of, "reason": "insufficient_cash"})
            continue
        notional = budget - _commission(budget)
        shares = notional / fill
        cost = notional + _commission(notional)
        cash -= cost
        positions[symbol] = {
            "entry_date": as_of,
            "signal_date": pending["signal_date"],
            "entry_price": round(fill, 6),
            "shares": round(shares, 8),
            "cost": round(cost, 6),
            "stop": pending["stop"],
        }

    positions_value = _positions_value(positions, series, as_of)
    nav = {
        "trade_date": as_of,
        "cash": round(cash, 6),
        "positions_value": round(positions_value, 6),
        "equity": round(cash + positions_value, 6),
        "positions": len(positions),
    }
    pool = [_pool_row(row) for row in screen_results[:POOL_SIZE]]
    pending_next = [
        {"symbol": row["symbol"], "signal_date": as_of, "stop": row["stop"]}
        for row in pool
        if row["state"] == "trigger" and row["symbol"] not in positions
    ]
    return {
        **state,
        "as_of": as_of,
        "cash": round(cash, 6),
        "positions": positions,
        "pending": pending_next,
        "pool": pool,
        "closed_trades": closed,
        "skipped_entries": skipped,
        "nav_history": [*state["nav_history"], nav],  # type: ignore[misc]
    }


def pool_metrics(state: Mapping[str, object]) -> dict[str, object]:
    history = list(state.get("nav_history") or [])
    trades = list(state.get("closed_trades") or [])
    initial = float(dict(state["config"])["initial_equity"])  # type: ignore[arg-type]
    peak, drawdown = initial, 0.0
    for row in history:
        peak = max(peak, float(row["equity"]))
        drawdown = max(drawdown, 1.0 - float(row["equity"]) / peak)
    wins = [t for t in trades if float(t["return"]) > 0]
    return {
        "sessions": len(history),
        "equity": float(history[-1]["equity"]) if history else initial,
        "total_return": (float(history[-1]["equity"]) / initial - 1.0) if history else 0.0,
        "max_drawdown": drawdown,
        "closed_trades": len(trades),
        "win_rate": len(wins) / len(trades) if trades else None,
        "average_trade_return": sum(float(t["return"]) for t in trades) / len(trades)
        if trades
        else None,
    }


def _pool_row(row: Mapping[str, object]) -> dict[str, object]:
    momentum = row.get("momentum") or {}
    return {
        "symbol": row["symbol"],
        "state": row["state"],
        "close": row.get("close"),
        "stop": row.get("stop"),
        "stop_pct": row.get("stop_pct"),
        "confluence": row.get("confluence"),
        "confluence_members": row.get("confluence_members"),
        "momentum_pct": momentum.get("momentum_pct"),  # type: ignore[union-attr]
        "reward_r": row.get("reward_r"),
    }


def _positions_value(
    positions: Mapping[str, Mapping[str, object]], series: Mapping[str, SymbolSeries], as_of: str
) -> float:
    total = 0.0
    for symbol, position in positions.items():
        item = series[symbol]
        index = _index(series, symbol, as_of)
        if index is None:
            earlier = [i for d, i in item.index_by_date.items() if d <= as_of]
            index = max(earlier)
        total += float(position["shares"]) * item.bars[index].close
    return total


def _index(series: Mapping[str, SymbolSeries], symbol: str, as_of: str) -> int | None:
    item = series.get(symbol)
    if item is None:
        return None
    index = item.index_by_date.get(as_of)
    return None if index is None or item.bars[index].suspended else index


def _limit(symbol: str) -> float:
    return 0.20 if symbol.startswith(("300", "301", "688", "689")) else 0.10


def _commission(notional: float) -> float:
    return max(MINIMUM_COMMISSION, notional * COMMISSION_RATE)
