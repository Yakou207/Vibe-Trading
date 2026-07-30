from __future__ import annotations

from fintech_quant.backtesting.costs import AShareCostModel
from fintech_quant.intraday.minute_data import bars_by_day, drop_corporate_action_days
from fintech_quant.intraday.rotation import (
    RotationParams,
    rotation_z_scores,
    run_rotation_day,
)

PARAMS = RotationParams(z_enter=1.5, z_exit=0.5, z_window=6, z_min_window=3)


def _bar(dt: str, price: float, volume: float = 1000.0, open_price: float | None = None):
    return {
        "datetime": dt,
        "open": open_price if open_price is not None else price,
        "high": price,
        "low": price,
        "close": price,
        "volume": volume,
    }


def _spike_day(direction: int = 1) -> list[dict[str, object]]:
    """Flat morning, a hard spike, then reversion to the mean."""
    day = "2026-07-20"
    prices = [10.0, 10.0, 10.01, 9.99, 10.0, 10.0]
    prices += [10.0 + 0.4 * direction]  # spike bar -> extreme z
    prices += [10.0 + 0.35 * direction]  # execution bar for the entry
    prices += [10.0, 10.0]  # reversion, exit fires
    prices += [10.0, 10.0]
    return [
        _bar(f"{day} {hh}:{mm:02d}:00", p)
        for p, (hh, mm) in zip(
            prices,
            [(9, 35), (9, 40), (9, 45), (9, 50), (9, 55), (10, 0), (10, 5), (10, 10), (10, 15), (10, 20), (10, 25), (10, 30)],
        )
    ]


def test_z_scores_need_min_window_and_flag_spikes() -> None:
    bars = _spike_day()
    scores = rotation_z_scores(bars, PARAMS)

    assert scores[0] is None and scores[1] is None  # window too short
    spike_index = 6
    assert scores[spike_index] is not None and scores[spike_index] > 1.5


def test_sell_high_buy_back_round_trip_is_profitable_and_balanced() -> None:
    result = run_rotation_day(_spike_day(1), base_shares=500, params=PARAMS)

    assert result.rounds == 1
    actions = [t["action"] for t in result.trades]
    assert actions == ["sell", "buy"]  # sold the spike, bought back the reversion
    assert result.end_shares_match_base
    assert result.enhancement_pnl > 0  # 0.35 CNY swing on 500 shares clears costs


def test_buy_low_leg_closes_by_selling_base_shares() -> None:
    result = run_rotation_day(_spike_day(-1), base_shares=500, params=PARAMS)

    assert [t["action"] for t in result.trades] == ["buy", "sell"]
    assert result.end_shares_match_base
    assert result.enhancement_pnl > 0


def test_signal_executes_on_next_bar_open_not_signal_bar() -> None:
    bars = _spike_day(1)
    result = run_rotation_day(bars, base_shares=500, params=PARAMS)

    sell = result.trades[0]
    assert sell["datetime"] == bars[7]["datetime"]  # bar AFTER the spike signal
    slip = RotationParams().slippage_rate
    assert sell["price"] == round(float(bars[7]["open"]) * (1 - slip), 6)


def test_t_plus_one_budget_allows_only_one_full_slice_round() -> None:
    # Two spike cycles in one day; the sellable budget must block the second.
    day = "2026-07-20"
    prices = [10.0, 10.0, 10.01, 9.99, 10.0, 10.0, 10.4, 10.35, 10.0, 10.0,
              10.0, 10.0, 10.4, 10.35, 10.0, 10.0, 10.0, 10.0]
    bars = [
        _bar(f"{day} 10:{mm:02d}:00" if mm < 60 else f"{day} 11:{mm - 60:02d}:00", p)
        for mm, p in zip(range(0, 90, 5), prices)
    ]
    result = run_rotation_day(bars, base_shares=500, params=PARAMS)

    assert result.rounds == 1  # budget spent, second spike ignored
    assert sum(t["shares"] for t in result.trades if t["action"] == "sell") <= 500
    assert result.end_shares_match_base


def test_open_leg_is_force_closed_before_the_close() -> None:
    day = "2026-07-20"
    # Spike late in the day; price never reverts, but the leg must still close.
    prices = [10.0, 10.0, 10.01, 9.99, 10.0, 10.0, 10.4, 10.38, 10.39, 10.4]
    times = ["14:20", "14:25", "14:30", "14:35", "14:40", "14:41", "14:42", "14:45", "14:50", "14:55"]
    bars = [_bar(f"{day} {t}:00", p) for t, p in zip(times, prices)]
    result = run_rotation_day(bars, base_shares=500, params=PARAMS)

    if result.trades:  # if a leg opened it must have closed
        assert result.end_shares_match_base
        assert len(result.trades) % 2 == 0


def test_costs_include_min_commission_and_sell_stamp_duty() -> None:
    result = run_rotation_day(_spike_day(1), base_shares=500, params=PARAMS)

    sell, buy = result.trades
    model = AShareCostModel()
    # ~5000 CNY notional -> min commission 5 CNY dominates 0.03%.
    assert result.total_cost >= 10.0
    assert result.total_cost == round(
        model.sell_cost(abs(sell["signed_notional"]), __import__("datetime").date(2026, 7, 20)).total
        + model.buy_cost(abs(buy["signed_notional"]), __import__("datetime").date(2026, 7, 20)).total,
        6,
    )


def test_no_trades_on_quiet_day() -> None:
    day = "2026-07-20"
    bars = [_bar(f"{day} 09:{35 + 5 * i % 60:02d}:00", 10.0 + 0.005 * (i % 3)) for i in range(20)]
    result = run_rotation_day(bars, base_shares=500, params=PARAMS)

    assert result.trades == []
    assert result.enhancement_pnl == 0.0


def test_corporate_action_day_dropped_by_gap_filter() -> None:
    day1 = [_bar("2026-07-20 09:35:00", 10.0), _bar("2026-07-20 15:00:00", 10.0)]
    day2 = [_bar("2026-07-21 09:35:00", 8.8, open_price=8.8), _bar("2026-07-21 15:00:00", 8.9)]  # -12% gap
    day3 = [_bar("2026-07-22 09:35:00", 8.85), _bar("2026-07-22 15:00:00", 8.9)]
    grouped = bars_by_day(day1 + day2 + day3)

    kept = drop_corporate_action_days(grouped)

    assert list(kept) == ["2026-07-20", "2026-07-22"]


def test_momentum_direction_buys_the_spike_and_closes_when_z_fades() -> None:
    params = RotationParams(
        z_enter=1.5, z_exit=0.5, z_window=6, z_min_window=3, direction="momentum"
    )
    result = run_rotation_day(_spike_day(1), base_shares=500, params=params)

    assert [t["action"] for t in result.trades] == ["buy", "sell"]  # follow, then fade out
    assert result.end_shares_match_base
    assert result.rounds == 1
