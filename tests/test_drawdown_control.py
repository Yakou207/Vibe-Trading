from __future__ import annotations

from datetime import date


def test_drawdown_control_reduces_at_eight_and_liquidates_at_ten_percent() -> None:
    from fintech_quant.backtesting.drawdown_control import (
        DrawdownControlState,
        DrawdownRegime,
        update_drawdown_control,
    )

    state = DrawdownControlState.initial(100.0)
    reduced = update_drawdown_control(
        state,
        trade_date=date(2026, 1, 2),
        actual_equity=92.0,
        shadow_equity=92.0,
    )
    liquidated = update_drawdown_control(
        reduced.state,
        trade_date=date(2026, 1, 3),
        actual_equity=89.9,
        shadow_equity=89.9,
    )

    assert reduced.state.regime is DrawdownRegime.REDUCED
    assert reduced.exposure_multiplier == 0.5
    assert liquidated.state.regime is DrawdownRegime.LIQUIDATED
    assert liquidated.exposure_multiplier == 0.0


def test_liquidated_control_uses_shadow_recovery_and_stages_reentry() -> None:
    from fintech_quant.backtesting.drawdown_control import (
        DrawdownControlState,
        DrawdownRegime,
        update_drawdown_control,
    )

    state = DrawdownControlState.initial(100.0)
    state = update_drawdown_control(
        state,
        trade_date=date(2026, 1, 2),
        actual_equity=89.0,
        shadow_equity=89.0,
    ).state
    still_out = update_drawdown_control(
        state,
        trade_date=date(2026, 1, 3),
        actual_equity=89.0,
        shadow_equity=91.0,
    )
    half_reentry = update_drawdown_control(
        still_out.state,
        trade_date=date(2026, 1, 4),
        actual_equity=89.0,
        shadow_equity=92.0,
    )
    full_reentry = update_drawdown_control(
        half_reentry.state,
        trade_date=date(2026, 1, 5),
        actual_equity=90.0,
        shadow_equity=94.0,
    )

    assert still_out.state.regime is DrawdownRegime.LIQUIDATED
    assert half_reentry.state.regime is DrawdownRegime.REDUCED
    assert half_reentry.state.actual_peak == 89.0
    assert half_reentry.exposure_multiplier == 0.5
    assert full_reentry.state.regime is DrawdownRegime.NORMAL
    assert full_reentry.exposure_multiplier == 1.0
    assert [event.to_regime for event in full_reentry.state.transitions] == [
        DrawdownRegime.LIQUIDATED,
        DrawdownRegime.REDUCED,
        DrawdownRegime.NORMAL,
    ]


def test_drawdown_control_state_round_trips_for_paper_account_persistence() -> None:
    from fintech_quant.backtesting.drawdown_control import (
        DrawdownControlState,
        drawdown_control_state_from_json,
        drawdown_control_state_to_json,
        update_drawdown_control,
    )

    state = update_drawdown_control(
        DrawdownControlState.initial(100.0),
        trade_date=date(2026, 1, 2),
        actual_equity=89.0,
        shadow_equity=89.0,
    ).state

    restored = drawdown_control_state_from_json(drawdown_control_state_to_json(state))

    assert restored == state
