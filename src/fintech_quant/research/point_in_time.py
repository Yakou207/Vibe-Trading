from __future__ import annotations

from bisect import bisect_right
from datetime import date
from typing import TYPE_CHECKING, Iterable, Sequence

from fintech_quant.data.historical_universe import MembershipInterval
from fintech_quant.data.symbols import normalize_a_share_symbol

if TYPE_CHECKING:
    from fintech_quant.research.dataset import SupplementalRow


class SupplementalAsOfIndex:
    def __init__(
        self,
        rows: Iterable[SupplementalRow],
        *,
        trading_dates: Sequence[date] = (),
        allow_undated: bool = False,
    ) -> None:
        grouped: dict[str, list[SupplementalRow]] = {}
        static: dict[str, SupplementalRow] = {}
        for row in rows:
            if row.trade_date is None:
                if not allow_undated:
                    raise ValueError("undated supplemental rows are not allowed in point-in-time mode")
                static[row.symbol] = row
                continue
            grouped.setdefault(row.symbol, []).append(row)
        self._rows = {
            symbol: tuple(sorted(items, key=lambda item: item.trade_date or date.min))
            for symbol, items in grouped.items()
        }
        self._dates = {
            symbol: tuple(item.trade_date for item in items if item.trade_date is not None)
            for symbol, items in self._rows.items()
        }
        self._static = static
        self._calendar_position = {
            trade_date: position for position, trade_date in enumerate(sorted(set(trading_dates)))
        }

    def lookup(
        self,
        symbol: str,
        signal_date: date,
        *,
        max_age_days: int | None = None,
        max_age_sessions: int | None = None,
    ) -> SupplementalRow | None:
        normalized = normalize_a_share_symbol(symbol)
        dates = self._dates.get(normalized, ())
        position = bisect_right(dates, signal_date) - 1
        if position < 0:
            return self._static.get(normalized)
        row = self._rows[normalized][position]
        available_date = row.trade_date
        if available_date is None:
            return self._static.get(normalized)
        if max_age_days is not None and (signal_date - available_date).days > max_age_days:
            return None
        if max_age_sessions is not None:
            signal_position = self._calendar_position.get(signal_date)
            row_position = self._calendar_position.get(available_date)
            if signal_position is None or row_position is None:
                return None
            if signal_position - row_position > max_age_sessions:
                return None
        return row


class MembershipAsOfIndex:
    def __init__(self, intervals: Iterable[MembershipInterval]) -> None:
        grouped: dict[str, list[MembershipInterval]] = {}
        for interval in intervals:
            grouped.setdefault(interval.symbol, []).append(interval)
        self._intervals = {
            symbol: tuple(sorted(items, key=lambda item: item.member_from))
            for symbol, items in grouped.items()
        }
        self._starts = {
            symbol: tuple(item.member_from for item in items)
            for symbol, items in self._intervals.items()
        }

    def is_active(self, symbol: str, on_date: date) -> bool:
        normalized = normalize_a_share_symbol(symbol)
        starts = self._starts.get(normalized, ())
        position = bisect_right(starts, on_date) - 1
        if position < 0:
            return False
        interval = self._intervals[normalized][position]
        return interval.member_to is None or on_date < interval.member_to
