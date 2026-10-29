from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from fintech_quant.reports.live_stock import SHANGHAI, LiveContext
from fintech_quant.reports.picker import PickerData, intraday_monitor_view
from fintech_quant.research import momentum_intraday as mi
from fintech_quant.research.momentum_setup import Bar, SymbolSeries, momentum_table, screen
from scripts.monitor_momentum_intraday import rebuild, watch, write_plan
from test_momentum_setup import _dates, _universe


T = _dates(200)[-1]  # reference session: 600001.SH triggers, 600005.SH is a setup
D, D1, D2 = _dates(205)[-3:]  # weekdays after T
RATIO = 0.5
WATCHLIST = [{"symbol": "600001.SH"}, {"symbol": "600005.SH"}, {"symbol": "600002.SH"}]


def _plan(**overrides: object) -> dict[str, object]:
    universe = _universe()
    arguments = {
        "session_date": D,
        "reference_session": T,
        "watchlist": WATCHLIST,
        "series": universe,
        "momentum": momentum_table(universe, T),
        "price_ratio": {s: RATIO for s in universe},
        "pool_as_of": T,
        **overrides,
    }
    return mi.build_plan(**arguments)  # type: ignore[arg-type]


def _entry(plan: dict[str, object], symbol: str = "600001.SH") -> dict[str, object]:
    return next(e for e in plan["names"] if e["symbol"] == symbol)  # type: ignore[union-attr]


def _points(*prices: float, start: str = "09:31", day: str = D) -> list[dict[str, object]]:
    first = datetime.fromisoformat(f"{day} {start}")
    return [
        {"time": (first + timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M"), "price": p}
        for i, p in enumerate(prices)
    ]


def _payload(points: list[dict[str, object]], day: str = D) -> dict[str, object]:
    return {"date": day, "source": "minute_em", "points": points}


# --- plan -------------------------------------------------------------------------------------


def test_plan_arms_setups_and_triggers_with_unadjusted_zone_and_limit() -> None:
    plan = _plan()
    leader = _entry(plan)

    assert leader["armed"] is True and leader["watch_state"] == "trigger"
    assert leader["zone"]["top"] == pytest.approx(round(leader["zone_hfq"]["top"] * RATIO, 3))
    assert len(leader["confluence_members"]) >= 2
    assert leader["prev_close"] == pytest.approx(round(_universe()["600001.SH"].bars[-1].close * RATIO, 3))
    assert leader["limit_up"] == pytest.approx(round(leader["prev_close"] * 1.1, 2), abs=0.01)
    assert _entry(plan, "600002.SH") == {
        "symbol": "600002.SH", "watch_state": "avoid", "armed": False, "reason": "state_avoid"
    }
    assert plan["counts_toward_evidence"] is False


def test_plan_needs_an_unadjusted_price_and_a_later_session() -> None:
    universe = _universe()
    plan = mi.build_plan(
        session_date=D, reference_session=T, watchlist=WATCHLIST, series=universe,
        momentum=momentum_table(universe, T), price_ratio={}, pool_as_of=T,
    )
    assert _entry(plan)["reason"] == "no_unadjusted_price"
    with pytest.raises(ValueError, match="must follow"):
        _plan(session_date=T)


# --- trigger and fill -------------------------------------------------------------------------


def test_trigger_needs_a_minute_in_the_zone_then_a_reclaim_above_its_top() -> None:
    entry = _entry(_plan())
    top = entry["zone"]["top"]

    assert mi.detect_trigger(entry, _points(top + 0.05, top + 0.08)) is None
    assert mi.detect_trigger(entry, _points(top + 0.05, top - 0.02, top - 0.04)) is None
    found = mi.detect_trigger(entry, _points(top + 0.05, top - 0.02, top - 0.04, top + 0.01))
    assert found == {
        "touch_time": f"{D} 09:32",
        "trigger_time": f"{D} 09:34",
        "trigger_price": top + 0.01,
        "low_so_far": top - 0.04,
    }


def test_reclaim_at_limit_up_is_not_a_trigger_until_price_leaves_the_limit() -> None:
    entry = {**_entry(_plan()), "limit_up": 10.40}
    top = entry["zone"]["top"]

    assert mi.detect_trigger(entry, _points(top - 0.01, 10.40)) is None
    assert mi.detect_trigger(entry, _points(top - 0.01, 10.40, 10.30))["trigger_time"] == f"{D} 09:33"


def test_fill_uses_the_next_minute_with_slippage_and_the_low_so_far_as_stop() -> None:
    plan = _plan()
    top = _entry(plan)["zone"]["top"]
    day = mi.initial_triggers(plan, "sha")
    minutes = _points(top + 0.05, top - 0.03, top + 0.02)

    day = mi.apply_poll(day, plan, {"600001.SH": _payload(minutes)}, polled_at="t1")
    assert day["triggers"]["600001.SH"]["status"] == "pending_fill"

    minutes = _points(top + 0.05, top - 0.03, top + 0.02, top + 0.04)
    day = mi.apply_poll(day, plan, {"600001.SH": _payload(minutes)}, polled_at="t2")
    trigger = day["triggers"]["600001.SH"]
    assert trigger["status"] == "filled" and trigger["fill_time"] == f"{D} 09:34"
    assert trigger["fill_price"] == pytest.approx((top + 0.04) * 1.0005)
    assert trigger["stop"] == pytest.approx(top - 0.03) and trigger["stop_capped"] is False
    assert day["polls"] == 2 and day["sources"] == {"600001.SH": "minute_em"}


def test_late_detection_fills_only_after_the_detecting_poll() -> None:
    plan = _plan()
    top = _entry(plan)["zone"]["top"]
    day = mi.initial_triggers(plan, "sha")
    late = _points(top - 0.03, top + 0.02, top + 0.06, top + 0.07)  # trigger at 09:32, seen at 09:34

    day = mi.apply_poll(day, plan, {"600001.SH": _payload(late)}, polled_at="t1")
    day = mi.apply_poll(day, plan, {"600001.SH": _payload([*late, *_points(top + 0.09, start="09:35")])}, polled_at="t2")

    assert day["triggers"]["600001.SH"]["fill_time"] == f"{D} 09:35"
    assert day["triggers"]["600001.SH"]["fill_raw"] == pytest.approx(top + 0.09)


def test_stop_is_capped_four_percent_below_the_fill() -> None:
    plan = _plan()
    top = _entry(plan)["zone"]["top"]
    day = mi.initial_triggers(plan, "sha")
    deep = _points(top - 1.0, top + 0.01)
    day = mi.apply_poll(day, plan, {"600001.SH": _payload(deep)}, polled_at="t1")
    day = mi.apply_poll(day, plan, {"600001.SH": _payload([*deep, *_points(top + 0.02, start="09:33")])}, polled_at="t2")

    trigger = day["triggers"]["600001.SH"]
    assert trigger["stop"] == pytest.approx(trigger["fill_price"] * 0.96)
    assert trigger["stop_capped"] is True


@pytest.mark.parametrize(
    ("fill", "reason"), [(10.40, "limit_up_fill"), (None, "fill_at_or_below_stop")]
)
def test_fill_at_limit_up_or_through_the_low_is_skipped(fill: float | None, reason: str) -> None:
    plan = _plan()
    entry = _entry(plan)
    entry["limit_up"] = 10.40
    top = entry["zone"]["top"]
    minutes = _points(top - 0.03, top + 0.01)
    day = mi.apply_poll(mi.initial_triggers(plan, "sha"), plan, {"600001.SH": _payload(minutes)}, polled_at="t1")
    price = fill if fill is not None else top - 0.03
    day = mi.apply_poll(day, plan, {"600001.SH": _payload([*minutes, *_points(price, start="09:33")])}, polled_at="t2")

    assert day["triggers"]["600001.SH"]["status"] == "skipped"
    assert day["triggers"]["600001.SH"]["skip_reason"] == reason


def test_previous_session_minutes_are_ignored_and_fetch_errors_are_recorded() -> None:
    plan = _plan()
    top = _entry(plan)["zone"]["top"]
    old = _payload(_points(top - 0.03, top + 0.01, day=T), day=T)

    day = mi.apply_poll(
        mi.initial_triggers(plan, "sha"),
        plan,
        {"600001.SH": old, "600005.SH": ConnectionError("proxy")},
        polled_at="t1",
    )

    assert day["triggers"] == {}
    assert day["errors"]["600005.SH"].startswith("t1 ConnectionError")


def test_a_trigger_still_waiting_at_the_close_is_unfilled() -> None:
    plan = _plan()
    top = _entry(plan)["zone"]["top"]
    day = mi.apply_poll(
        mi.initial_triggers(plan, "sha"), plan,
        {"600001.SH": _payload(_points(top - 0.03, top + 0.01, start="14:59"))}, polled_at="t1",
    )
    day = mi.finalize_day(day)

    assert day["finalized"] is True
    assert day["triggers"]["600001.SH"]["status"] == "unfilled"


@pytest.mark.parametrize(
    ("now", "due"),
    [
        ("09:00:00", "09:30:20"),
        ("10:00:05", "10:00:20"),
        ("10:00:30", "10:01:20"),
        ("11:31:00", "11:31:20"),
        ("11:32:00", "13:00:20"),
        ("15:01:10", "15:01:20"),
        ("15:01:30", None),
    ],
)
def test_polls_run_each_minute_in_both_half_sessions(now: str, due: str | None) -> None:
    result = mi.next_poll(datetime.fromisoformat(f"{D} {now}"))
    assert (None if result is None else result.strftime("%H:%M:%S")) == due


# --- ledger -----------------------------------------------------------------------------------


def _extended() -> dict[str, SymbolSeries]:
    """D flushes into the zone and reclaims (a daily trigger), D+1 closes under the 9 EMA and
    D+2 gaps below the D low."""
    universe = _universe()
    result = {}
    for symbol, item in universe.items():
        bars = list(item.bars)
        last = bars[-1].close
        if symbol != "600001.SH":
            bars += [Bar(d, last, last * 1.01, last * 0.99, last, 1e6) for d in (D, D1, D2)]
        else:
            draft = SymbolSeries(symbol, bars + [bars[-1]])
            low, high = sorted((draft.ema9[-1], draft.ema21[-1]))
            close = max(high * 1.004, last * 1.002)
            bars.append(Bar(D, high * 1.001, close * 1.002, low * 0.99, close, 2e6))
            bars.append(Bar(D1, close, close * 1.001, close * 0.9905, close * 0.991, 1e6))
            bars.append(Bar(D2, low * 0.98, low * 0.985, low * 0.97, low * 0.975, 1e6))
        result[symbol] = SymbolSeries(symbol, bars)
    return result


def _filled_day(plan: dict[str, object]) -> dict[str, object]:
    top = _entry(plan)["zone"]["top"]
    minutes = _points(top + 0.05, top - 0.01, top + 0.02)
    day = mi.apply_poll(mi.initial_triggers(plan, "sha"), plan, {"600001.SH": _payload(minutes)}, polled_at="t1")
    return mi.apply_poll(day, plan, {"600001.SH": _payload([*minutes, *_points(top + 0.03, start="09:34")])}, polled_at="t2")


def _ledger(as_of: str) -> dict[str, object]:
    series = _extended()
    plan = _plan()
    return mi.build_ledger(
        [(plan, _filled_day(plan))],
        series=series,
        momentum_for=lambda d: momentum_table(series, d),
        as_of=as_of,
    )


def test_daily_trigger_fixture_is_a_trigger_on_d() -> None:
    assert screen(_extended(), D)[0]["state"] == "trigger"


def test_intraday_leg_never_exits_on_its_entry_day() -> None:
    signal = _ledger(D)["signals"][0]
    intraday = signal["intraday"]

    assert intraday["status"] == "open" and intraday["entry_date"] == D
    assert _extended()["600001.SH"].bars[-3].low < intraday["stop"]  # D's low is under the stop
    assert intraday["entry_price"] == pytest.approx(_filled_day(_plan())["triggers"]["600001.SH"]["fill_price"] / RATIO)
    assert signal["daily"]["status"] == "pending_entry"


def test_both_legs_follow_the_v1_daily_exits_from_the_session_after_entry() -> None:
    ledger = _ledger(D2)
    signal = ledger["signals"][0]
    item = _extended()["600001.SH"]
    bar_d1, bar_d2 = item.bars[-2], item.bars[-1]

    intraday, daily = signal["intraday"], signal["daily"]
    assert (intraday["status"], intraday["exit_date"], intraday["reason"]) == (
        "closed", D1, "close_below_ema9"
    )
    assert intraday["exit_price"] == pytest.approx(bar_d1.close * (1 - mi.SLIPPAGE_RATE))
    assert daily["entry_date"] == D1
    assert daily["entry_price"] == pytest.approx(bar_d1.open * (1 + mi.SLIPPAGE_RATE))
    assert (daily["status"], daily["exit_date"], daily["reason"]) == ("closed", D2, "gap_below_stop")
    assert daily["exit_price"] == pytest.approx(bar_d2.open * (1 - mi.SLIPPAGE_RATE))
    expected = intraday["exit_price"] * (1 - 0.0003 - 0.0005) / (intraday["entry_price"] * 1.0003) - 1
    assert intraday["return"] == pytest.approx(expected, abs=1e-6)

    result = mi.comparison(ledger)
    assert result["both_entered"] == 1 and result["intraday_only"] == 0
    assert result["mean_entry_gap"] == pytest.approx(intraday["entry_price"] / daily["entry_price"] - 1)
    assert result["intraday_closed"]["count"] == 1 and result["daily_closed"]["count"] == 1
    assert "| " + D + " | 600001.SH |" in mi.comparison_markdown(result)


def test_plans_after_the_latest_session_wait_for_daily_data() -> None:
    ledger = _ledger(T)
    assert ledger["signals"] == [] and ledger["pending_days"] == [D]


# --- script and picker ------------------------------------------------------------------------


def _picker_data(series: dict[str, SymbolSeries], as_of: str) -> PickerData:
    return PickerData(
        as_of=as_of, series=series, names={"600001.SH": "领涨股份"}, members=set(series),
        scores={}, market_warnings={}, price_ratio={s: RATIO for s in series},
        screen_results=screen(series, as_of), momentum=momentum_table(series, as_of), sources={},
    )


def test_plan_is_written_once_and_requires_a_current_pool(tmp_path: Path) -> None:
    data = _picker_data(_universe(), T)
    pool = {"as_of": T, "watchlist": WATCHLIST}

    path = write_plan(data, pool, tmp_path, D)
    assert write_plan(data, pool, tmp_path, D) == path  # identical rerun is accepted
    with pytest.raises(ValueError, match="already exists"):
        write_plan(data, {**pool, "watchlist": WATCHLIST[:1]}, tmp_path, D)
    with pytest.raises(ValueError, match="refresh_momentum_pool_v2"):
        write_plan(data, {**pool, "as_of": "2024-01-01"}, tmp_path, D1)
    with pytest.raises(ValueError, match="evidence"):
        write_plan(data, pool, tmp_path / "validation", D)


def test_watch_polls_through_the_session_with_injected_fetchers(tmp_path: Path) -> None:
    write_plan(_picker_data(_universe(), T), {"as_of": T, "watchlist": WATCHLIST}, tmp_path, D)
    top = _entry(json.loads((tmp_path / D / "plan.json").read_text()))["zone"]["top"]
    prices = [top + 0.05, top - 0.01, top + 0.02, top + 0.03] + [top + 0.04] * 300
    clock = [datetime.fromisoformat(f"{D} 09:29:00").replace(tzinfo=SHANGHAI)]
    calls = []

    def minute_em(symbol: str) -> list[dict[str, object]]:
        calls.append(symbol)
        open_ = clock[0].replace(hour=9, minute=30, second=0)
        elapsed = int((clock[0] - open_).total_seconds() // 60)
        if clock[0].hour >= 13:
            elapsed -= 89  # lunch break
        count = min(max(elapsed, 0), 240)
        return [
            {"时间": p["time"], "收盘": p["price"], "成交量": 1.0, "均价": p["price"]}
            for p in _points(*prices[:count])
        ]

    def sleep(seconds: float) -> None:
        clock[0] += timedelta(seconds=seconds)

    live = LiveContext(cache_dir=None, fetchers={"minute_em": minute_em})
    day = watch(tmp_path, D, live, now=lambda: clock[0], sleep=sleep)

    assert day["finalized"] is True and set(calls) == {"600001", "600005"}
    assert day["polls"] == 2 * 122  # 09:30:20-11:31:20 and 13:00:20-15:01:20, once a minute
    trigger = day["triggers"]["600001.SH"]
    assert (trigger["trigger_time"], trigger["fill_time"]) == (f"{D} 09:33", f"{D} 09:34")
    saved = json.loads((tmp_path / D / "triggers.json").read_text())
    assert saved == json.loads(json.dumps(day))


def test_watch_refuses_another_day(tmp_path: Path) -> None:
    write_plan(_picker_data(_universe(), T), {"as_of": T, "watchlist": WATCHLIST}, tmp_path, D)
    with pytest.raises(ValueError, match="forward-only"):
        watch(tmp_path, D, LiveContext(cache_dir=None), now=lambda: datetime.fromisoformat(f"{D1} 10:00"))


def test_rebuild_writes_ledger_comparison_and_note(tmp_path: Path) -> None:
    plan_data = _picker_data(_universe(), T)
    write_plan(plan_data, {"as_of": T, "watchlist": WATCHLIST}, tmp_path, D)
    plan_path = tmp_path / D / "plan.json"
    plan = json.loads(plan_path.read_text())
    import hashlib

    day = {**_filled_day(plan), "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest()}
    (tmp_path / D / "triggers.json").write_text(json.dumps(day))

    result = rebuild(_picker_data(_extended(), D2), tmp_path)

    assert result["both_entered"] == 1
    assert json.loads((tmp_path / "ledger.json").read_text())["as_of"] == D2
    assert "Intraday vs next-open" in (tmp_path / "comparison.md").read_text()

    view = intraday_monitor_view(plan_data, plan, day, result)
    assert view["names"][0]["name"] == "领涨股份"
    assert view["names"][0]["trigger"]["status"] == "filled"
    assert view["comparison"]["both_entered"] == 1
