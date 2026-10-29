"""Forward-only intraday trigger monitor for the shadow momentum pool v2 watchlist.

Research only. It measures how an intraday Luk-style entry (buy on the reclaim, stop at the day's
low so far) differs from the predeclared daily rule (confirm at the close, buy at the next open).
It never reads or writes the counted paper account, pipeline state or evidence files, and it does
not change the v1/v2 pool rules. It is not backtested on history: minute data covers only a few
days, so evidence accumulates forward from the first recorded plan.

1. Plan (pre-market, session D). For each v2 watchlist name, ``analyze_at`` on the latest
   pipeline session T gives the confluence zone (9/21/50 EMA, AVWAPs from the six-month swing
   low/high, prior pivot, unfilled gap) and the reference levels. They are hfq levels; the plan
   also stores them on the unadjusted scale (hfq x unadjusted/hfq close ratio at T) because the
   minute data is unadjusted. A name is armed when its T state is ``setup`` or ``trigger`` and it
   has a zone of at least two supports.
2. Trigger (during D). On 1-minute prices: a minute at or below the zone top (into the zone), then
   a later minute above the zone top (reclaim) that is not at the limit-up price. Minute prices are
   minute closes, so "low so far" is the lowest minute close, not the exact tick low.
3. Fill. The first minute that appears after the poll that detected the trigger (normally the
   next minute), plus the counted 0.05% slippage. A fill at the limit-up price or at or below the
   low so far is skipped. The stop is the low so far, raised to 4% below the fill when the low is
   further away (``stop_capped`` records it).
4. Ledger. Each armed name and session D gives a signal with up to two legs, both exited with the
   v1 daily rule (open at or below the stop sells at the open, a low through the stop sells at the
   stop, otherwise a close under the 9 EMA sells at the close), evaluated from the session after
   entry (A-share T+1):
   - ``intraday``: entered on D at the simulated fill.
   - ``daily``: the same name's daily rule at D's close; when D is a ``trigger`` it buys at the
     next session's open with v1's skip rules (suspended, limit-up open, open at or below stop).
   Returns use hfq prices, the 0.03% commission rate (no CNY 5 minimum: legs have no notional),
   0.05% sell stamp duty and 0.05% slippage per fill. The ledger is rebuilt from the plan and
   trigger files plus the latest point-in-time daily data, so it never carries hidden state.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Callable, Mapping, Sequence

from fintech_quant.research.momentum_pool import (
    COMMISSION_RATE,
    SLIPPAGE_RATE,
    STAMP_DUTY_RATE,
    _limit,
)
from fintech_quant.research.momentum_setup import SetupConfig, SymbolSeries, analyze_at

ARMED_STATES = ("setup", "trigger")
MAX_STOP_PCT = SetupConfig().max_stop_pct
LIMIT_TOLERANCE = 0.995  # as in v1: within 0.5% of the limit price counts as limit-up
SESSIONS = ((time(9, 30), time(11, 30)), (time(13, 0), time(15, 0)))


def build_plan(
    *,
    session_date: str,
    reference_session: str,
    watchlist: Sequence[Mapping[str, object]],
    series: Mapping[str, SymbolSeries],
    momentum: Mapping[str, Mapping[str, float]],
    price_ratio: Mapping[str, float],
    pool_as_of: object,
) -> dict[str, object]:
    if session_date <= reference_session:
        raise ValueError(f"plan date {session_date} must follow session {reference_session}")
    names = []
    for row in watchlist:
        symbol = str(row["symbol"])
        item = series.get(symbol)
        analysis = (
            analyze_at(item, reference_session, momentum.get(symbol))
            if item is not None
            else {"state": "no_bar"}
        )
        ratio = price_ratio.get(symbol)
        zone = analysis.get("zone")
        entry: dict[str, object] = {
            "symbol": symbol,
            "watch_state": analysis["state"],
            "armed": False,
        }
        if analysis["state"] not in ARMED_STATES:
            entry["reason"] = f"state_{analysis['state']}"
        elif zone is None or int(analysis.get("confluence") or 0) < SetupConfig().min_confluence:
            entry["reason"] = "no_confluence_zone"
        elif ratio is None:
            entry["reason"] = "no_unadjusted_price"
        else:
            prev_close = float(analysis["close"]) * ratio  # type: ignore[arg-type]
            entry.update(
                {
                    "armed": True,
                    "ratio": ratio,
                    "zone_hfq": dict(zone),  # type: ignore[arg-type]
                    "zone": {k: round(float(v) * ratio, 3) for k, v in dict(zone).items()},  # type: ignore[arg-type]
                    "confluence_members": analysis["confluence_members"],
                    "supports": {
                        k: round(float(v) * ratio, 3)
                        for k, v in dict(analysis["supports"]).items()  # type: ignore[arg-type]
                    },
                    "prev_close": round(prev_close, 3),
                    "limit_up": round(prev_close * (1 + _limit(symbol)), 2),
                }
            )
        names.append(entry)
    return {
        "schema_version": 1,
        "kind": "momentum_intraday_plan",
        "counts_toward_evidence": False,
        "date": session_date,
        "reference_session": reference_session,
        "pool_as_of": pool_as_of,
        "names": names,
        "rules": {
            "trigger": "minute price <= zone top, then a later minute > zone top below limit-up",
            "fill": "first minute after the detecting poll, plus slippage",
            "slippage_rate": SLIPPAGE_RATE,
            "max_stop_pct": MAX_STOP_PCT,
        },
    }


def detect_trigger(
    entry: Mapping[str, object], points: Sequence[Mapping[str, object]]
) -> dict[str, object] | None:
    """First reclaim of the zone top after a minute in the zone; ``None`` until it happens."""
    top = float(dict(entry["zone"])["top"])  # type: ignore[arg-type]
    limit_up = float(entry["limit_up"])  # type: ignore[arg-type]
    touch = None
    low = float("inf")
    for point in points:
        price = float(point["price"])  # type: ignore[arg-type]
        low = min(low, price)
        if price <= top:
            touch = touch or str(point["time"])
        elif touch is not None and price < limit_up * LIMIT_TOLERANCE:
            return {
                "touch_time": touch,
                "trigger_time": str(point["time"]),
                "trigger_price": price,
                "low_so_far": low,
            }
    return None


def initial_triggers(plan: Mapping[str, object], plan_sha256: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "momentum_intraday_triggers",
        "counts_toward_evidence": False,
        "date": plan["date"],
        "plan_sha256": plan_sha256,
        "polls": 0,
        "last_poll_at": None,
        "finalized": False,
        "sources": {},
        "errors": {},
        "triggers": {},
    }


def apply_poll(
    day: Mapping[str, object],
    plan: Mapping[str, object],
    minutes: Mapping[str, Mapping[str, object] | Exception],
    *,
    polled_at: str,
) -> dict[str, object]:
    """One poll: record new triggers and fill pending ones. ``minutes`` maps a symbol to the
    ``live_intraday`` payload, or the exception its fetch raised."""
    triggers = {s: dict(t) for s, t in dict(day["triggers"]).items()}  # type: ignore[arg-type]
    sources = dict(day["sources"])  # type: ignore[arg-type]
    errors = dict(day["errors"])  # type: ignore[arg-type]
    for entry in plan["names"]:  # type: ignore[union-attr]
        symbol = str(entry["symbol"])
        if not entry["armed"] or symbol not in minutes:
            continue
        payload = minutes[symbol]
        if isinstance(payload, Exception):
            errors[symbol] = f"{polled_at} {type(payload).__name__}: {str(payload)[:160]}"
            continue
        if payload.get("date") != plan["date"]:
            continue  # the source still serves the previous session
        points = sorted(payload.get("points") or [], key=lambda p: str(p["time"]))  # type: ignore[arg-type]
        if not points:
            continue
        sources[symbol] = str(payload.get("source"))
        current = triggers.get(symbol)
        if current is None:
            found = detect_trigger(entry, points)
            if found is not None:
                triggers[symbol] = {
                    **found,
                    "detected_at": polled_at,
                    "detected_last_minute": str(points[-1]["time"]),
                    "status": "pending_fill",
                }
        elif current["status"] == "pending_fill":
            later = [p for p in points if str(p["time"]) > str(current["detected_last_minute"])]
            if later:
                triggers[symbol] = _fill(current, entry, later[0])
    return {
        **day,
        "polls": int(day["polls"]) + 1,  # type: ignore[arg-type]
        "last_poll_at": polled_at,
        "sources": sources,
        "errors": errors,
        "triggers": triggers,
    }


def finalize_day(day: Mapping[str, object]) -> dict[str, object]:
    triggers = {}
    for symbol, trigger in dict(day["triggers"]).items():  # type: ignore[arg-type]
        trigger = dict(trigger)
        if trigger["status"] == "pending_fill":
            trigger.update({"status": "unfilled", "skip_reason": "session_ended"})
        triggers[symbol] = trigger
    return {**day, "triggers": triggers, "finalized": True}


def _fill(
    trigger: Mapping[str, object], entry: Mapping[str, object], point: Mapping[str, object]
) -> dict[str, object]:
    raw = float(point["price"])  # type: ignore[arg-type]
    low = float(trigger["low_so_far"])  # type: ignore[arg-type]
    result = {**trigger, "fill_time": str(point["time"]), "fill_raw": raw}
    if raw >= float(entry["limit_up"]) * LIMIT_TOLERANCE:  # type: ignore[arg-type]
        return {**result, "status": "skipped", "skip_reason": "limit_up_fill"}
    if raw <= low:
        return {**result, "status": "skipped", "skip_reason": "fill_at_or_below_stop"}
    fill = raw * (1 + SLIPPAGE_RATE)
    cap = fill * (1 - MAX_STOP_PCT)
    return {
        **result,
        "status": "filled",
        "fill_price": round(fill, 6),
        "stop": round(max(low, cap), 6),
        "stop_capped": low < cap,
    }


# --- forward ledger ---------------------------------------------------------------------------


def build_ledger(
    days: Sequence[tuple[Mapping[str, object], Mapping[str, object] | None]],
    *,
    series: Mapping[str, SymbolSeries],
    momentum_for: Callable[[str], Mapping[str, Mapping[str, float]]],
    as_of: str,
) -> dict[str, object]:
    """Rebuild every signal from (plan, triggers) pairs and point-in-time daily bars to ``as_of``.

    ``momentum_for(date)`` returns the cross-sectional momentum table for that session."""
    calendar = sorted({b.trade_date for item in series.values() for b in item.bars})
    signals = []
    pending_days = []
    for plan, day in sorted(days, key=lambda pair: str(pair[0]["date"])):
        session = str(plan["date"])
        if session > as_of:
            pending_days.append(session)
            continue
        table = momentum_for(session) if session in calendar else {}
        for entry in plan["names"]:  # type: ignore[union-attr]
            if not entry["armed"]:
                continue
            symbol = str(entry["symbol"])
            item = series.get(symbol)
            trigger = dict((day or {}).get("triggers", {})).get(symbol)  # type: ignore[union-attr]
            intraday = None if trigger is None else _intraday_leg(trigger, entry, session)
            daily = None
            if item is not None and session in calendar:
                analysis = analyze_at(item, session, table.get(symbol))
                if analysis["state"] == "trigger":
                    daily = _daily_leg(item, session, float(analysis["stop"]), calendar, as_of)  # type: ignore[arg-type]
            for leg in (intraday, daily):
                if leg is not None and leg["status"] == "open" and item is not None:
                    _advance(leg, item, as_of)
            if intraday is None and daily is None:
                continue
            signals.append({"date": session, "symbol": symbol, "intraday": intraday, "daily": daily})
    return {
        "schema_version": 1,
        "kind": "momentum_intraday_ledger",
        "counts_toward_evidence": False,
        "as_of": as_of,
        "plan_days": sorted(str(plan["date"]) for plan, _ in days),
        "pending_days": pending_days,
        "signals": signals,
        "config": {
            "exit_rule": "v1: stop at open/intraday, else close below ema9; from the next session",
            "price_basis": "hfq",
            "commission_rate": COMMISSION_RATE,
            "stamp_duty_rate": STAMP_DUTY_RATE,
            "slippage_rate": SLIPPAGE_RATE,
        },
    }


def _intraday_leg(
    trigger: Mapping[str, object], entry: Mapping[str, object], session: str
) -> dict[str, object]:
    leg = {
        "entry_kind": "intraday",
        "trigger_time": trigger.get("trigger_time"),
        "detected_at": trigger.get("detected_at"),
        "fill_time": trigger.get("fill_time"),
    }
    if trigger["status"] != "filled":
        return {**leg, "status": "skipped", "reason": trigger.get("skip_reason", "unfilled")}
    ratio = float(entry["ratio"])  # type: ignore[arg-type]
    entry_price = float(trigger["fill_price"]) / ratio  # type: ignore[arg-type]
    stop = float(trigger["stop"]) / ratio  # type: ignore[arg-type]
    return {
        **leg,
        "status": "open",
        "entry_date": session,
        "entry_price": round(entry_price, 6),
        "entry_price_unadjusted": trigger["fill_price"],
        "stop": round(stop, 6),
        "stop_pct": 1 - stop / entry_price,
        "stop_capped": trigger.get("stop_capped"),
    }


def _daily_leg(
    item: SymbolSeries, session: str, stop: float, calendar: Sequence[str], as_of: str
) -> dict[str, object]:
    later = [d for d in calendar if d > session]
    leg: dict[str, object] = {"entry_kind": "next_open", "signal_date": session, "stop": stop}
    if not later or later[0] > as_of:
        return {**leg, "status": "pending_entry"}
    entry_date = later[0]
    index = item.index_by_date.get(entry_date)
    if index is None or item.bars[index].suspended:
        return {**leg, "status": "skipped", "reason": "suspended", "entry_date": entry_date}
    bar = item.bars[index]
    if bar.open >= item.bars[index - 1].close * (1 + _limit(item.symbol)) * LIMIT_TOLERANCE:
        return {**leg, "status": "skipped", "reason": "limit_up_open", "entry_date": entry_date}
    if bar.open <= stop:
        return {**leg, "status": "skipped", "reason": "gapped_below_stop", "entry_date": entry_date}
    entry_price = bar.open * (1 + SLIPPAGE_RATE)
    return {
        **leg,
        "status": "open",
        "entry_date": entry_date,
        "entry_price": round(entry_price, 6),
        "stop_pct": 1 - stop / entry_price,
    }


def _advance(leg: dict[str, object], item: SymbolSeries, as_of: str) -> None:
    """v1 daily exits for the sessions after entry up to ``as_of`` (T+1: never on entry day)."""
    stop = float(leg["stop"])  # type: ignore[arg-type]
    held = 0
    for index, bar in enumerate(item.bars):
        if bar.trade_date <= str(leg["entry_date"]) or bar.trade_date > as_of or bar.suspended:
            continue
        held += 1
        if bar.open <= stop:
            price, reason = bar.open, "gap_below_stop"
        elif bar.low <= stop:
            price, reason = stop, "stop"
        elif bar.close < item.ema9[index]:
            price, reason = bar.close, "close_below_ema9"
        else:
            leg.update({"last_close": bar.close, "sessions_held": held})
            leg["unrealized"] = _net_return(float(leg["entry_price"]), bar.close)  # type: ignore[arg-type]
            continue
        exit_price = price * (1 - SLIPPAGE_RATE)
        leg.pop("last_close", None)
        leg.pop("unrealized", None)
        leg.update(
            {
                "status": "closed",
                "exit_date": bar.trade_date,
                "exit_price": round(exit_price, 6),
                "reason": reason,
                "sessions_held": held,
                "return": round(_net_return(float(leg["entry_price"]), exit_price), 6),  # type: ignore[arg-type]
            }
        )
        return


def _net_return(entry_price: float, exit_price: float) -> float:
    cost = entry_price * (1 + COMMISSION_RATE)
    return exit_price * (1 - COMMISSION_RATE - STAMP_DUTY_RATE) / cost - 1.0


# --- comparison -------------------------------------------------------------------------------


def comparison(ledger: Mapping[str, object]) -> dict[str, object]:
    signals = list(ledger["signals"])  # type: ignore[arg-type]

    def entered(leg: object) -> bool:
        return isinstance(leg, Mapping) and leg.get("status") in {"open", "closed"}

    both = [s for s in signals if entered(s["intraday"]) and entered(s["daily"])]
    pairs = []
    for signal in both:
        intraday, daily = signal["intraday"], signal["daily"]
        pairs.append(
            {
                "date": signal["date"],
                "symbol": signal["symbol"],
                "entry_gap": intraday["entry_price"] / daily["entry_price"] - 1.0,
                "intraday_stop_pct": intraday["stop_pct"],
                "daily_stop_pct": daily["stop_pct"],
                "intraday": _outcome(intraday),
                "daily": _outcome(daily),
            }
        )
    return {
        "as_of": ledger["as_of"],
        "plan_days": len(list(ledger["plan_days"])),  # type: ignore[arg-type]
        "signals": len(signals),
        "intraday_triggers": sum(1 for s in signals if s["intraday"] is not None),
        "intraday_entries": sum(1 for s in signals if entered(s["intraday"])),
        "daily_triggers": sum(1 for s in signals if s["daily"] is not None),
        "daily_entries": sum(1 for s in signals if entered(s["daily"])),
        "both_entered": len(pairs),
        "intraday_only": sum(1 for s in signals if entered(s["intraday"]) and s["daily"] is None),
        "daily_only": sum(1 for s in signals if entered(s["daily"]) and s["intraday"] is None),
        "mean_entry_gap": _mean([p["entry_gap"] for p in pairs]),
        "intraday_closed": _closed_stats([s["intraday"] for s in signals if entered(s["intraday"])]),
        "daily_closed": _closed_stats([s["daily"] for s in signals if entered(s["daily"])]),
        "pairs": pairs,
    }


def comparison_markdown(result: Mapping[str, object]) -> str:
    lines = [
        "# Intraday vs next-open entries (shadow pool v2 watchlist)",
        "",
        f"Generated from the forward ledger as of {result['as_of']}. Research only; not evidence.",
        "Both legs exit with the v1 daily rule from the session after entry. Small samples: do",
        "not read a difference as an edge until many signals have closed.",
        "",
        f"- Plan days: {result['plan_days']}; signals: {result['signals']}",
        f"- Intraday triggers: {result['intraday_triggers']} (entered {result['intraday_entries']})",
        f"- Daily triggers: {result['daily_triggers']} (entered {result['daily_entries']})",
        f"- Same signal, both entered: {result['both_entered']}; intraday only: "
        f"{result['intraday_only']}; daily only: {result['daily_only']}",
        f"- Mean intraday entry vs next open: {_pct(result['mean_entry_gap'])}",
    ]
    for key, label in (("intraday_closed", "Intraday"), ("daily_closed", "Next open")):
        stats = dict(result[key])  # type: ignore[arg-type]
        lines.append(
            f"- {label} closed legs: {stats['count']}, mean return {_pct(stats['mean_return'])}, "
            f"win rate {_pct(stats['win_rate'])}"
        )
    pairs = list(result["pairs"])  # type: ignore[arg-type]
    if pairs:
        lines += [
            "",
            "| Date | Symbol | Entry gap | Stop (intraday / next open) | Intraday | Next open |",
            "|---|---|---|---|---|---|",
        ]
        for p in pairs:
            lines.append(
                f"| {p['date']} | {p['symbol']} | {_pct(p['entry_gap'])} | "
                f"{_pct(p['intraday_stop_pct'])} / {_pct(p['daily_stop_pct'])} | "
                f"{p['intraday']} | {p['daily']} |"
            )
    return "\n".join(lines) + "\n"


def _outcome(leg: Mapping[str, object]) -> str:
    if leg["status"] == "closed":
        return f"{leg['reason']} {_pct(leg['return'])}"
    return f"open {_pct(leg.get('unrealized'))}"


def _closed_stats(legs: Sequence[Mapping[str, object]]) -> dict[str, object]:
    returns = [float(leg["return"]) for leg in legs if leg["status"] == "closed"]  # type: ignore[arg-type]
    return {
        "count": len(returns),
        "mean_return": _mean(returns),
        "win_rate": sum(1 for r in returns if r > 0) / len(returns) if returns else None,
    }


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _pct(value: object) -> str:
    return "—" if value is None else f"{float(value):+.2%}"  # type: ignore[arg-type]


def next_poll(now: datetime) -> datetime | None:
    """Next poll time, 20 s into each minute so the minute just closed is published; the last
    poll of each half-day is one minute after its close. ``None`` once the session is over."""
    offset = timedelta(seconds=20)

    def at(moment: time) -> datetime:
        return now.replace(hour=moment.hour, minute=moment.minute, second=0, microsecond=0)

    candidate = now.replace(second=0, microsecond=0) + offset
    if candidate <= now:
        candidate += timedelta(minutes=1)
    for start, end in SESSIONS:
        if candidate < at(start) + offset:
            return at(start) + offset
        if candidate <= at(end) + timedelta(minutes=1) + offset:
            return candidate
    return None
