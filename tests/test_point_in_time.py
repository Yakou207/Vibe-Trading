from __future__ import annotations

from datetime import date

import pytest


def test_as_of_lookup_never_uses_future_disclosure() -> None:
    from fintech_quant.research.dataset import SupplementalRow
    from fintech_quant.research.point_in_time import SupplementalAsOfIndex

    index = SupplementalAsOfIndex(
        [
            SupplementalRow("000001.SZ", date(2026, 4, 24), {"pe": 18.0}),
            SupplementalRow("000001.SZ", date(2026, 8, 20), {"pe": 1.0}),
        ]
    )

    row = index.lookup("000001.SZ", date(2026, 6, 30), max_age_days=180)

    assert row is not None
    assert row.values["pe"] == 18.0


def test_as_of_lookup_rejects_stale_and_undated_formal_rows() -> None:
    from fintech_quant.research.dataset import SupplementalRow
    from fintech_quant.research.point_in_time import SupplementalAsOfIndex

    with pytest.raises(ValueError, match="undated supplemental rows"):
        SupplementalAsOfIndex([SupplementalRow("000001.SZ", None, {"pe": 18.0})])

    index = SupplementalAsOfIndex(
        [SupplementalRow("000001.SZ", date(2025, 1, 1), {"pe": 18.0})]
    )
    assert index.lookup("000001.SZ", date(2026, 1, 1), max_age_days=180) is None


def test_as_of_lookup_uses_trading_sessions_for_capital_flow_age() -> None:
    from fintech_quant.research.dataset import SupplementalRow
    from fintech_quant.research.point_in_time import SupplementalAsOfIndex

    trading_dates = tuple(date(2026, 1, day) for day in (2, 5, 6, 7, 8))
    index = SupplementalAsOfIndex(
        [SupplementalRow("000001.SZ", date(2026, 1, 2), {"main_net_inflow": 100.0})],
        trading_dates=trading_dates,
    )

    assert index.lookup("000001.SZ", date(2026, 1, 7), max_age_sessions=3) is not None
    assert index.lookup("000001.SZ", date(2026, 1, 8), max_age_sessions=3) is None


def test_membership_index_hides_addition_before_effective_date() -> None:
    from fintech_quant.data.historical_universe import MembershipInterval
    from fintech_quant.research.point_in_time import MembershipAsOfIndex

    index = MembershipAsOfIndex(
        [
            MembershipInterval(
                "000300",
                "000002.SZ",
                date(2026, 6, 1),
                date(2026, 6, 15),
                "csindex",
                "2026-07-10T12:00:00+08:00",
            ),
            MembershipInterval(
                "000300",
                "600519.SH",
                date(2026, 6, 15),
                None,
                "csindex",
                "2026-07-10T12:00:00+08:00",
            ),
        ]
    )

    assert index.is_active("000002.SZ", date(2026, 6, 14)) is True
    assert index.is_active("600519.SH", date(2026, 6, 14)) is False
    assert index.is_active("600519.SH", date(2026, 6, 15)) is True
