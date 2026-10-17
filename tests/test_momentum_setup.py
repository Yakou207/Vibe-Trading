from __future__ import annotations

from datetime import date, timedelta

import pytest

from fintech_quant.research.momentum_pool import initial_pool_state, pool_metrics, step_pool
from fintech_quant.research.momentum_setup import (
    Bar,
    SymbolSeries,
    analyze_at,
    ema,
    momentum_table,
    screen,
)


START = date(2025, 1, 1)


def _dates(n: int) -> list[str]:
    return [(START + timedelta(days=i)).isoformat() for i in range(n)]


def _bars(closes: list[float], *, spread: float = 0.01) -> list[Bar]:
    days = _dates(len(closes))
    return [
        Bar(d, c, c * (1 + spread), c * (1 - spread), c, 1_000_000.0) for d, c in zip(days, closes)
    ]


def _leader_with_flush() -> SymbolSeries:
    """Trend up, eight-week rising base, then a bar that flushes into the EMA cluster and reclaims."""
    closes = [10 + 0.07 * i for i in range(140)]
    closes += [19.6 + 0.4 * ((i % 6) / 5) + 0.012 * i for i in range(59)]
    bars = _bars(closes)
    draft = SymbolSeries("600001.SH", bars + [bars[-1]])
    zone_low = min(draft.ema9[-2], draft.ema21[-2])
    zone_high = max(draft.ema9[-2], draft.ema21[-2])
    last_close = max(zone_high * 1.004, bars[-1].close * 1.002)
    bars.append(
        Bar(
            _dates(200)[-1],
            zone_high * 1.001,
            last_close * 1.002,
            zone_low * 0.998,
            last_close,
            2e6,
        )
    )
    return SymbolSeries("600001.SH", bars)


def _universe() -> dict[str, SymbolSeries]:
    universe = {"600001.SH": _leader_with_flush()}
    for k, slope in enumerate((-0.02, -0.01, 0.0, 0.005)):
        universe[f"60000{k + 2}.SH"] = SymbolSeries(
            f"60000{k + 2}.SH", _bars([20 + slope * i for i in range(200)])
        )
    return universe


def test_ema_matches_recursive_definition() -> None:
    assert ema([1.0, 2.0, 3.0], 3) == pytest.approx([1.0, 1.5, 2.25])


def test_momentum_percentiles_rank_the_trend_leader_first() -> None:
    universe = _universe()
    table = momentum_table(universe, _dates(200)[-1])

    assert table["600001.SH"]["momentum_pct"] == pytest.approx(1.0)
    assert table["600002.SH"]["momentum_pct"] == pytest.approx(0.0)


def test_flush_into_confluence_and_reclaim_is_a_trigger_with_tight_stop() -> None:
    universe = _universe()
    as_of = _dates(200)[-1]
    table = momentum_table(universe, as_of)

    result = analyze_at(universe["600001.SH"], as_of, table["600001.SH"])

    assert result["state"] == "trigger", result["checks"]
    assert result["confluence"] >= 2
    assert result["stop"] == universe["600001.SH"].bars[-1].low
    assert 0 < result["stop_pct"] <= 0.04
    assert [check["passed"] for check in result["checks"]] == [True, True, True, True]


def test_downtrend_is_avoided_with_reason() -> None:
    universe = _universe()
    as_of = _dates(200)[-1]
    table = momentum_table(universe, as_of)

    result = analyze_at(universe["600002.SH"], as_of, table["600002.SH"])

    assert result["state"] == "avoid"
    assert result["checks"][0]["passed"] is False


def test_screen_orders_triggers_first_and_skips_non_members() -> None:
    universe = _universe()
    as_of = _dates(200)[-1]

    results = screen(universe, as_of, members={"600001.SH", "600002.SH"})

    assert [row["symbol"] for row in results] == ["600001.SH", "600002.SH"]


def test_suspended_or_missing_bar_is_not_analysed() -> None:
    universe = _universe()
    item = universe["600003.SH"]
    item.bars[-1] = Bar(item.bars[-1].trade_date, 1, 1, 1, 1, 0, suspended=True)

    assert analyze_at(item, item.bars[-1].trade_date, None)["state"] == "no_bar"
    assert "600003.SH" not in momentum_table(universe, item.bars[-1].trade_date)


def _pool_series(rows: list[tuple[str, float, float, float, float]]) -> dict[str, SymbolSeries]:
    history = [Bar(d, 10, 10.1, 9.9, 10, 1e6) for d in _dates(30)[: -len(rows)]]
    bars = history + [Bar(d, o, h, low, c, 1e6) for d, o, h, low, c in rows]
    return {"600001.SH": SymbolSeries("600001.SH", bars)}


def _trigger(symbol: str = "600001.SH", stop: float = 9.5) -> dict[str, object]:
    return {"symbol": symbol, "state": "trigger", "stop": stop, "close": 10.0, "momentum": {}}


def test_pool_buys_next_open_and_cannot_exit_same_day() -> None:
    days = _dates(30)
    series = _pool_series([(days[-2], 10, 10.2, 9.8, 10), (days[-1], 10.1, 10.2, 9.0, 9.2)])
    state = step_pool(
        initial_pool_state(),
        as_of=days[-2],
        series=series,
        screen_results=[_trigger()],
        previous_session=days[-3],
    )
    assert state["pending"][0]["symbol"] == "600001.SH"

    state = step_pool(
        state, as_of=days[-1], series=series, screen_results=[], previous_session=days[-2]
    )

    position = state["positions"]["600001.SH"]
    assert position["entry_date"] == days[-1]
    assert position["entry_price"] == pytest.approx(10.1 * 1.0005)
    assert state["closed_trades"] == []


def test_pool_exits_at_stop_after_entry_day() -> None:
    days = _dates(30)
    series = _pool_series(
        [
            (days[-3], 10, 10.2, 9.8, 10),
            (days[-2], 10.1, 10.3, 10.0, 10.2),
            (days[-1], 10.0, 10.1, 9.4, 9.6),
        ]
    )
    state = step_pool(
        initial_pool_state(),
        as_of=days[-3],
        series=series,
        screen_results=[_trigger()],
        previous_session=days[-4],
    )
    state = step_pool(
        state, as_of=days[-2], series=series, screen_results=[], previous_session=days[-3]
    )
    state = step_pool(
        state, as_of=days[-1], series=series, screen_results=[], previous_session=days[-2]
    )

    assert state["positions"] == {}
    assert state["closed_trades"][0]["reason"] == "stop"
    assert state["closed_trades"][0]["exit_price"] == pytest.approx(9.5 * (1 - 0.0005))
    assert pool_metrics(state)["closed_trades"] == 1


def test_pool_skips_gap_below_stop_limit_up_open_and_stale_signals() -> None:
    days = _dates(30)
    gap = _pool_series([(days[-2], 10, 10.2, 9.8, 10), (days[-1], 9.4, 9.6, 9.3, 9.5)])
    state = step_pool(
        initial_pool_state(),
        as_of=days[-2],
        series=gap,
        screen_results=[_trigger()],
        previous_session=days[-3],
    )
    state = step_pool(
        state, as_of=days[-1], series=gap, screen_results=[], previous_session=days[-2]
    )
    assert state["skipped_entries"][-1]["reason"] == "gapped_below_stop"

    limit = _pool_series([(days[-2], 10, 10.2, 9.8, 10), (days[-1], 11.0, 11.0, 11.0, 11.0)])
    state = step_pool(
        initial_pool_state(),
        as_of=days[-2],
        series=limit,
        screen_results=[_trigger()],
        previous_session=days[-3],
    )
    state = step_pool(
        state, as_of=days[-1], series=limit, screen_results=[], previous_session=days[-2]
    )
    assert state["skipped_entries"][-1]["reason"] == "limit_up_open"

    state = step_pool(
        initial_pool_state(),
        as_of=days[-3],
        series=gap,
        screen_results=[_trigger()],
        previous_session=days[-4],
    )
    state = step_pool(
        state, as_of=days[-1], series=gap, screen_results=[], previous_session=days[-2]
    )
    assert state["skipped_entries"][-1]["reason"] == "stale_signal"


def test_pool_rejects_duplicate_or_out_of_order_refresh() -> None:
    days = _dates(30)
    series = _pool_series([(days[-1], 10, 10.2, 9.8, 10)])
    state = step_pool(
        initial_pool_state(),
        as_of=days[-1],
        series=series,
        screen_results=[],
        previous_session=None,
    )

    with pytest.raises(ValueError, match="must follow"):
        step_pool(state, as_of=days[-1], series=series, screen_results=[], previous_session=None)


def test_pool_keeps_only_top_five_and_queues_only_triggers() -> None:
    days = _dates(30)
    series = _pool_series([(days[-1], 10, 10.2, 9.8, 10)])
    results = [_trigger(f"60000{i}.SH") for i in range(4)] + [
        {"symbol": f"60001{i}.SH", "state": "setup", "stop": 9, "momentum": {}} for i in range(4)
    ]

    state = step_pool(
        initial_pool_state(),
        as_of=days[-1],
        series=series,
        screen_results=results,
        previous_session=None,
    )

    assert len(state["pool"]) == 5
    assert [p["symbol"] for p in state["pending"]] == [f"60000{i}.SH" for i in range(4)]
    assert state["counts_toward_evidence"] is False
