from __future__ import annotations

from datetime import date

import pytest


def test_reconstructs_membership_backward_without_seeing_future_addition() -> None:
    from fintech_quant.data.historical_universe import (
        MembershipAdjustment,
        MembershipAnchor,
        active_symbols,
        build_membership_intervals,
    )

    anchor = MembershipAnchor(
        index_code="000300",
        as_of=date(2026, 6, 15),
        symbols=("000001.SZ", "600000.SH", "600519.SH"),
        source="csindex",
        source_fetched_at="2026-07-10T12:00:00+08:00",
    )
    adjustments = (
        MembershipAdjustment(
            effective_date=date(2026, 6, 15),
            removed_symbol="000002.SZ",
            added_symbol="600519.SH",
            source_url="https://official.example/adjustment.pdf",
        ),
    )

    intervals = build_membership_intervals(
        anchor,
        adjustments,
        start=date(2026, 6, 1),
        expected_members=3,
    )

    assert active_symbols(intervals, date(2026, 6, 14)) == (
        "000001.SZ",
        "000002.SZ",
        "600000.SH",
    )
    assert active_symbols(intervals, date(2026, 6, 15)) == (
        "000001.SZ",
        "600000.SH",
        "600519.SH",
    )


def test_reconstruction_rejects_adjustment_missing_added_member_from_anchor() -> None:
    from fintech_quant.data.historical_universe import (
        MembershipAdjustment,
        MembershipAnchor,
        build_membership_intervals,
    )

    anchor = MembershipAnchor(
        index_code="000300",
        as_of=date(2026, 6, 15),
        symbols=("000001.SZ", "600000.SH", "600519.SH"),
        source="csindex",
        source_fetched_at="2026-07-10T12:00:00+08:00",
    )
    bad_adjustment = MembershipAdjustment(
        effective_date=date(2026, 6, 15),
        removed_symbol="000002.SZ",
        added_symbol="601318.SH",
        source_url="https://official.example/adjustment.pdf",
    )

    with pytest.raises(ValueError, match="added symbol is not active after adjustment"):
        build_membership_intervals(
            anchor,
            (bad_adjustment,),
            start=date(2026, 6, 1),
            expected_members=3,
        )


def test_reconstruction_rejects_wrong_anchor_member_count() -> None:
    from fintech_quant.data.historical_universe import MembershipAnchor, build_membership_intervals

    anchor = MembershipAnchor(
        index_code="000300",
        as_of=date(2026, 6, 15),
        symbols=("000001.SZ", "600000.SH"),
        source="csindex",
        source_fetched_at="2026-07-10T12:00:00+08:00",
    )

    with pytest.raises(ValueError, match="expected 3 active members, found 2"):
        build_membership_intervals(
            anchor,
            (),
            start=date(2026, 6, 1),
            expected_members=3,
        )
