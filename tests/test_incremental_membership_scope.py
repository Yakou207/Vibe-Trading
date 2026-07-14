from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable

import pytest

from scripts.collect_corporate_actions import _membership_symbols as action_symbols
from scripts.collect_historical_prices import _membership_symbols as price_symbols
from scripts.collect_point_in_time_factors import _membership_symbols as factor_symbols


@pytest.mark.parametrize("selector", [price_symbols, factor_symbols, action_symbols])
def test_incremental_collectors_only_request_members_overlapping_date_range(
    tmp_path: Path, selector: Callable[[Path, date, date], tuple[str, ...]]
) -> None:
    membership = tmp_path / "membership.csv"
    membership.write_text(
        "index_code,symbol,member_from,member_to,source,source_fetched_at\n"
        "000300,600001.SH,2021-01-01,2025-01-01,fixture,2026-01-01T00:00:00Z\n"
        "000300,600002.SH,2025-01-01,,fixture,2026-01-01T00:00:00Z\n"
        "000300,600003.SH,2027-01-01,,fixture,2026-01-01T00:00:00Z\n",
        encoding="utf-8",
    )

    selected = selector(membership, date(2026, 7, 14), date(2026, 7, 14))

    assert selected == ("600002.SH",)
