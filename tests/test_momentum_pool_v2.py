from __future__ import annotations

from datetime import date, timedelta

import pytest

from fintech_quant.research.momentum_pool_v2 import (
    SLIPPAGE_RATE,
    exit_decision,
    initial_pool_state,
    performance,
    pool_metrics,
    position_status,
    size_entry,
    step_pool,
)
from fintech_quant.research.momentum_setup import Bar, SymbolSeries


START = date(2025, 1, 1)
POSITION = {"entry_price": 100.0, "stop": 98.0, "peak_close": 100.0, "sessions_held": 1}


def _days(n: int) -> list[str]:
    return [(START + timedelta(days=i)).isoformat() for i in range(n)]


def _series(symbol: str, ohlc: list[tuple[float, float, float, float]]) -> SymbolSeries:
    return SymbolSeries(
        symbol, [Bar(d, o, h, low, c, 1e6) for d, (o, h, low, c) in zip(_days(len(ohlc)), ohlc)]
    )


def _flat(n: int, price: float = 100.0) -> list[tuple[float, float, float, float]]:
    return [(price, price * 1.01, price * 0.99, price)] * n


def _row(symbol: str, state: str, stop: float = 98.0, close: float = 100.5) -> dict[str, object]:
    return {
        "symbol": symbol,
        "state": state,
        "close": close,
        "stop": stop,
        "stop_pct": 1 - stop / close,
        "confluence": 2,
        "momentum": {"momentum_pct": 0.9},
    }


def _exit(position: dict[str, object] | None = None, **bar: object) -> tuple[float, str] | None:
    values = {
        "bar_open": 100.0,
        "bar_low": 99.0,
        "bar_close": 100.5,
        "ema9": 100.0,
        "ema21": 99.0,
        "screen_state": "setup",
        **bar,
    }
    return exit_decision({**POSITION, **(position or {})}, **values)  # type: ignore[arg-type]


def _step(state, day, series, rows, previous):  # type: ignore[no-untyped-def]
    return step_pool(state, as_of=day, series=series, screen_results=rows, previous_session=previous)


# --- exit rules -----------------------------------------------------------------------------


def test_open_at_or_below_stop_exits_at_the_open() -> None:
    assert _exit(bar_open=97.0, bar_low=96.0) == (97.0, "gap_below_stop")
    assert _exit(bar_open=98.0, bar_low=97.0) == (98.0, "gap_below_stop")


def test_low_through_stop_exits_at_the_stop() -> None:
    assert _exit(bar_low=97.5, bar_close=101.0) == (98.0, "stop")


def test_close_below_ema9_exits_before_2r() -> None:
    assert _exit(bar_close=99.5, ema9=100.0) == (99.5, "close_below_ema9")
    assert _exit(bar_close=100.5, ema9=100.0) is None


def test_after_2r_the_trail_moves_to_ema21() -> None:
    reached = {"peak_close": 104.5}  # peak 2.25R
    assert _exit(reached, bar_close=103.0, ema9=103.5, ema21=102.0) is None
    assert _exit(reached, bar_close=103.0, ema9=103.5, ema21=103.2) == (103.0, "close_below_ema21")


def test_profit_giveback_after_2r() -> None:
    reached = {"peak_close": 108.0}  # peak 4R
    assert _exit(reached, bar_close=104.0, ema9=103.0, ema21=101.0) == (104.0, "profit_giveback")
    assert _exit(reached, bar_close=104.2, ema9=103.0, ema21=101.0) is None
    below_2r = {"peak_close": 103.9}  # peak 1.95R, give-back not armed
    assert _exit(below_2r, bar_close=101.0, ema9=100.0) is None


def test_time_stop_after_15_sessions_below_1r() -> None:
    assert _exit({"sessions_held": 15}, bar_close=101.0) == (101.0, "time_stop")
    assert _exit({"sessions_held": 14}, bar_close=101.0) is None
    assert _exit({"sessions_held": 15, "peak_close": 102.5}, bar_close=102.5) is None


def test_avoid_state_invalidates_at_the_close() -> None:
    assert _exit(screen_state="avoid") == (100.5, "invalidated")


def test_exit_rules_apply_in_predeclared_order() -> None:
    assert _exit(bar_open=97.0, bar_low=96.0, bar_close=99.0, screen_state="avoid")[1] == (  # type: ignore[index]
        "gap_below_stop"
    )
    assert _exit(bar_close=99.5, screen_state="avoid")[1] == "close_below_ema9"  # type: ignore[index]
    assert _exit({"sessions_held": 20}, screen_state="avoid")[1] == "time_stop"  # type: ignore[index]


def test_position_status_reports_r_and_armed_rules() -> None:
    status = position_status(
        {**POSITION, "peak_close": 105.0, "sessions_held": 3}, close=104.0, ema9=103.0, ema21=101.0
    )
    assert status["r_multiple"] == pytest.approx(2.0)
    assert status["trail"] == "ema21"
    assert status["giveback_exit_r"] == pytest.approx(1.25)
    assert status["time_stop_in"] == 12


# --- sizing ---------------------------------------------------------------------------------


def test_full_risk_sizing_is_capped_at_15_percent() -> None:
    notional, shares = size_entry(
        equity=100000.0, cash=100000.0, fill=100.0, stop=98.0, multiplier=1.0
    )
    assert notional == pytest.approx(15000.0)  # uncapped risk size would be 37,500
    assert shares == pytest.approx(150.0)


def test_risk_sizing_binds_below_the_cap_and_halves_under_the_brake() -> None:
    notional, _ = size_entry(equity=100000.0, cash=100000.0, fill=100.0, stop=96.5, multiplier=0.5)
    assert notional == pytest.approx(0.00375 * 100000 / 0.035)


def test_sizing_is_capped_by_cash() -> None:
    notional, _ = size_entry(equity=100000.0, cash=4000.0, fill=100.0, stop=98.0, multiplier=1.0)
    assert notional == pytest.approx(3995.0)


# --- integration: T+1, skips, watchlist ------------------------------------------------------


def _trade_fixture(day32: tuple[float, float, float, float]) -> dict[str, SymbolSeries]:
    ohlc = _flat(30) + [(100.0, 101.0, 98.0, 100.5), (100.2, 100.8, 97.5, 100.4), day32]
    return {"600001.SH": _series("600001.SH", ohlc)}


def test_trigger_buys_next_open_at_capped_risk_size_and_cannot_exit_same_day() -> None:
    days = _days(33)
    series = _trade_fixture((99.0, 100.0, 97.0, 99.5))
    state = _step(initial_pool_state(), days[30], series, [_row("600001.SH", "trigger")], days[29])
    assert state["book"]["pending"] == [
        {"symbol": "600001.SH", "signal_date": days[30], "stop": 98.0}
    ]

    state = _step(state, days[31], series, [_row("600001.SH", "setup")], days[30])
    position = state["book"]["positions"]["600001.SH"]
    assert position["entry_price"] == pytest.approx(100.2 * (1 + SLIPPAGE_RATE))
    assert position["weight"] == pytest.approx(0.15)
    assert state["book"]["closed_trades"] == []  # low 97.5 broke the stop on the entry day
    assert all(row["symbol"] != "600001.SH" for row in state["watchlist"])

    state = _step(state, days[32], series, [_row("600001.SH", "setup")], days[31])
    trade = state["book"]["closed_trades"][0]
    assert trade["reason"] == "stop"
    assert trade["exit_price"] == pytest.approx(98.0 * (1 - SLIPPAGE_RATE))
    assert trade["r_multiple"] < -1.0


def test_avoid_state_invalidates_a_held_position_through_the_refresh() -> None:
    days = _days(33)
    series = _trade_fixture((100.5, 101.5, 100.0, 101.0))
    state = _step(initial_pool_state(), days[30], series, [_row("600001.SH", "trigger")], days[29])
    state = _step(state, days[31], series, [_row("600001.SH", "setup")], days[30])
    state = _step(state, days[32], series, [_row("600001.SH", "avoid")], days[31])
    assert [t["reason"] for t in state["book"]["closed_trades"]] == ["invalidated"]


def test_wide_stop_at_the_fill_skips_the_entry() -> None:
    days = _days(33)
    series = _trade_fixture((100.0, 101.0, 99.0, 100.0))
    state = _step(
        initial_pool_state(), days[30], series, [_row("600001.SH", "trigger", stop=96.0)], days[29]
    )
    state = _step(state, days[31], series, [], days[30])
    assert state["book"]["positions"] == {}
    assert state["book"]["skipped_entries"][-1]["reason"] == "stop_too_wide"


def test_watchlist_expires_after_10_sessions_without_triggering() -> None:
    days = _days(12)
    fillers = [_row(f"F{k}", "setup") for k in range(5)]
    state = _step(initial_pool_state(), days[0], {}, [_row("A", "setup")], None)
    for i in range(1, 10):  # A is still screened as a setup, just outside the top five
        state = _step(state, days[i], {}, [*fillers, _row("A", "setup")], days[i - 1])
    assert {r["symbol"]: r["age"] for r in state["watchlist"]}["A"] == 9
    state = _step(state, days[10], {}, [*fillers, _row("A", "setup")], days[9])
    assert "A" not in {r["symbol"] for r in state["watchlist"]}


def test_trigger_or_top5_reappearance_resets_age_and_avoid_removes() -> None:
    days = _days(6)
    state = _step(initial_pool_state(), days[0], {}, [_row("A", "setup"), _row("B", "setup")], None)
    state = _step(state, days[1], {}, [], days[0])
    state = _step(state, days[2], {}, [*[_row(f"F{i}", "setup") for i in range(5)], _row("A", "trigger")], days[1])
    ages = {r["symbol"]: r["age"] for r in state["watchlist"]}
    assert ages["A"] == 0 and ages["B"] == 2
    assert state["book"]["pending"][0]["symbol"] == "A"
    state = _step(state, days[3], {}, [_row("B", "setup"), _row("A", "avoid")], days[2])
    ages = {r["symbol"]: r["age"] for r in state["watchlist"]}
    assert "A" not in ages and ages["B"] == 0


def test_watchlist_cap_evicts_the_oldest_first() -> None:
    days = _days(5)
    state, previous = initial_pool_state(), None
    for d, day in enumerate(days):
        rows = [_row(f"S{d}{k}", "setup") for k in range(5)]
        state = _step(state, day, {}, rows, previous)
        previous = day
    symbols = {r["symbol"] for r in state["watchlist"]}
    assert len(symbols) == 20
    assert not any(s.startswith("S0") for s in symbols)
    assert {f"S4{k}" for k in range(5)} <= symbols


# --- brake ----------------------------------------------------------------------------------


def _brake_state(regime: str, actual_cash: float, actual_peak: float) -> dict[str, object]:
    state = initial_pool_state()
    state["book"] = {**state["book"], "cash": actual_cash, "nav_history": [
        {"trade_date": "2024-12-31", "equity": actual_cash, "positions_value": 0.0}
    ]}
    state["brake"] = {**state["brake"], "regime": regime, "actual_peak": actual_peak}
    return state


def test_brake_halves_risk_after_8_percent_drawdown() -> None:
    days = _days(33)
    series = _trade_fixture((100.5, 101.5, 100.0, 101.0))
    state = _brake_state("normal", 91000.0, 100000.0)
    state = _step(state, days[30], series, [_row("600001.SH", "trigger", stop=97.0)], days[29])
    assert state["brake"]["regime"] == "reduced"
    state = _step(state, days[31], series, [], days[30])
    position = state["book"]["positions"]["600001.SH"]
    assert position["risk_multiplier"] == 0.5
    expected = 0.00375 * 91000.0 / (1 - 97.0 / position["entry_price"])
    assert position["cost"] == pytest.approx(expected + 5.0, rel=1e-4)
    assert state["shadow_book"]["positions"]["600001.SH"]["weight"] == pytest.approx(0.15)


def test_brake_blocks_entries_above_10_percent_drawdown() -> None:
    days = _days(33)
    series = _trade_fixture((100.5, 101.5, 100.0, 101.0))
    state = _brake_state("normal", 89000.0, 100000.0)
    state = _step(state, days[30], series, [_row("600001.SH", "trigger")], days[29])
    assert state["brake"]["regime"] == "liquidated"
    state = _step(state, days[31], series, [], days[30])
    assert state["book"]["positions"] == {}
    assert state["book"]["skipped_entries"][-1]["reason"] == "brake_no_entries"
    assert "600001.SH" in state["shadow_book"]["positions"]


def test_brake_recovers_in_stages_on_the_unrestricted_shadow_book() -> None:
    days = _days(4)
    rising = [(100.0, 101.0, 99.0, 100.0), (100.0, 101.0, 99.0, 100.0), (120, 121, 119, 120), (150, 151, 149, 150)]
    series = {"X": _series("X", rising)}
    state = _brake_state("liquidated", 89000.0, 100000.0)
    state["shadow_book"] = {**state["shadow_book"], "cash": 80000.0, "positions": {"X": {
        "entry_date": "2024-12-01", "signal_date": "2024-11-30", "entry_price": 100.0,
        "shares": 100.0, "cost": 10000.0, "stop": 50.0, "peak_close": 100.0, "sessions_held": 0,
    }}}
    regimes = []
    for i in range(1, 4):
        state = _step(state, days[i], series, [], days[i - 1])
        regimes.append(state["brake"]["regime"])
    # shadow drawdowns: 10% (stay), 8% (-> reduced), 5% (-> normal)
    assert regimes == ["liquidated", "reduced", "normal"]
    assert [row["brake"] for row in state["book"]["nav_history"][1:]] == regimes


# --- metrics --------------------------------------------------------------------------------


def test_performance_excludes_a_window_and_overlapping_trades() -> None:
    history = [
        {"trade_date": "2024-09-10", "equity": 101000.0, "positions_value": 50500.0},
        {"trade_date": "2024-09-20", "equity": 121200.0, "positions_value": 0.0},
        {"trade_date": "2024-11-05", "equity": 115140.0, "positions_value": 0.0},
    ]
    trades = [
        {"entry_date": "2024-09-09", "exit_date": "2024-09-20", "return": 0.2, "reason": "stop"},
        {"entry_date": "2024-11-01", "exit_date": "2024-11-05", "return": -0.05, "reason": "time_stop"},
    ]
    full = performance(history, trades)
    cut = performance(history, trades, exclude=("2024-09-15", "2024-10-31"))
    assert full["total_return"] == pytest.approx(0.1514)
    assert cut["total_return"] == pytest.approx(1.01 * 0.95 - 1)
    assert cut["trades"] == 1 and cut["exits_by_reason"] == {"time_stop": 1}
    assert cut["average_exposure"] == pytest.approx(0.25)


def test_refresh_must_move_forward() -> None:
    state = _step(initial_pool_state(), "2025-01-02", {}, [], None)
    with pytest.raises(ValueError):
        _step(state, "2025-01-02", {}, [], None)
    assert pool_metrics(state)["brake"] == "normal"
