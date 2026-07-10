from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence

from fintech_quant.data.symbols import normalize_a_share_symbol


MEMBERSHIP_FIELDS = (
    "index_code",
    "symbol",
    "member_from",
    "member_to",
    "source",
    "source_fetched_at",
)


@dataclass(frozen=True)
class MembershipAnchor:
    index_code: str
    as_of: date
    symbols: tuple[str, ...]
    source: str
    source_fetched_at: str

    def __post_init__(self) -> None:
        normalized = tuple(sorted(normalize_a_share_symbol(symbol) for symbol in self.symbols))
        if len(normalized) != len(set(normalized)):
            raise ValueError("anchor contains duplicate symbols")
        if not self.source.strip():
            raise ValueError("anchor source is required")
        object.__setattr__(self, "symbols", normalized)


@dataclass(frozen=True)
class MembershipAdjustment:
    effective_date: date
    removed_symbol: str
    added_symbol: str
    source_url: str

    def __post_init__(self) -> None:
        if not self.source_url.strip():
            raise ValueError("source_url is required")
        object.__setattr__(self, "removed_symbol", normalize_a_share_symbol(self.removed_symbol))
        object.__setattr__(self, "added_symbol", normalize_a_share_symbol(self.added_symbol))


@dataclass(frozen=True)
class MembershipInterval:
    index_code: str
    symbol: str
    member_from: date
    member_to: date | None
    source: str
    source_fetched_at: str

    def __post_init__(self) -> None:
        if self.member_to is not None and self.member_to <= self.member_from:
            raise ValueError("member_to must be later than member_from")
        object.__setattr__(self, "symbol", normalize_a_share_symbol(self.symbol))


def build_membership_intervals(
    anchor: MembershipAnchor,
    adjustments: Sequence[MembershipAdjustment],
    *,
    start: date,
    expected_members: int = 300,
) -> tuple[MembershipInterval, ...]:
    if expected_members <= 0:
        raise ValueError("expected_members must be positive")
    if start > anchor.as_of:
        raise ValueError("start must not be later than anchor as_of")

    active = set(anchor.symbols)
    _require_member_count(active, expected_members, anchor.as_of)
    grouped = _group_adjustments(adjustments, start, anchor.as_of)
    periods: list[tuple[date, date | None, frozenset[str]]] = []
    period_end: date | None = None

    for effective_date in sorted(grouped, reverse=True):
        periods.append((effective_date, period_end, frozenset(active)))
        changes = grouped[effective_date]
        added = {change.added_symbol for change in changes}
        removed = {change.removed_symbol for change in changes}
        if len(added) != len(changes) or len(removed) != len(changes):
            raise ValueError(f"duplicate adjustment symbol on {effective_date.isoformat()}")
        missing_added = sorted(added - active)
        if missing_added:
            raise ValueError(
                f"added symbol is not active after adjustment on {effective_date.isoformat()}: {missing_added[0]}"
            )
        retained_removed = sorted(removed & active)
        if retained_removed:
            raise ValueError(
                f"removed symbol remains active after adjustment on {effective_date.isoformat()}: "
                f"{retained_removed[0]}"
            )
        active.difference_update(added)
        active.update(removed)
        _require_member_count(active, expected_members, effective_date)
        period_end = effective_date

    if period_end is None or start < period_end:
        periods.append((start, period_end, frozenset(active)))

    return _intervals_from_periods(anchor, periods)


def active_symbols(intervals: Sequence[MembershipInterval], on_date: date) -> tuple[str, ...]:
    return tuple(
        sorted(
            interval.symbol
            for interval in intervals
            if interval.member_from <= on_date
            and (interval.member_to is None or on_date < interval.member_to)
        )
    )


def load_membership_anchor(
    path: Path,
    *,
    index_code: str,
    source_fetched_at: str,
) -> MembershipAnchor:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("anchor CSV must contain at least one row")
    as_of_values = {str(row.get("as_of", "")).strip() for row in rows}
    source_values = {str(row.get("source", "")).strip() for row in rows}
    if "" in as_of_values or len(as_of_values) != 1:
        raise ValueError("anchor CSV must contain one non-empty as_of date")
    if "" in source_values or len(source_values) != 1:
        raise ValueError("anchor CSV must contain one non-empty source")
    symbols = tuple(str(row.get("symbol", "")).strip() for row in rows)
    if any(not symbol for symbol in symbols):
        raise ValueError("anchor CSV contains an empty symbol")
    return MembershipAnchor(
        index_code=index_code,
        as_of=date.fromisoformat(as_of_values.pop()),
        symbols=symbols,
        source=source_values.pop(),
        source_fetched_at=source_fetched_at,
    )


def load_membership_adjustments(path: Path) -> tuple[MembershipAdjustment, ...]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return tuple(
        MembershipAdjustment(
            effective_date=date.fromisoformat(str(row.get("effective_date", "")).strip()),
            removed_symbol=str(row.get("removed_symbol", "")).strip(),
            added_symbol=str(row.get("added_symbol", "")).strip(),
            source_url=str(row.get("source_url", "")).strip(),
        )
        for row in rows
    )


def write_membership_csv(path: Path, intervals: Iterable[MembershipInterval]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MEMBERSHIP_FIELDS)
        writer.writeheader()
        for interval in sorted(intervals, key=lambda item: (item.symbol, item.member_from)):
            writer.writerow(
                {
                    "index_code": interval.index_code,
                    "symbol": interval.symbol,
                    "member_from": interval.member_from.isoformat(),
                    "member_to": interval.member_to.isoformat() if interval.member_to else "",
                    "source": interval.source,
                    "source_fetched_at": interval.source_fetched_at,
                }
            )


def _group_adjustments(
    adjustments: Sequence[MembershipAdjustment],
    start: date,
    anchor_date: date,
) -> dict[date, list[MembershipAdjustment]]:
    grouped: dict[date, list[MembershipAdjustment]] = {}
    for adjustment in adjustments:
        if adjustment.effective_date > anchor_date:
            raise ValueError("adjustment effective_date must not be later than anchor as_of")
        if adjustment.effective_date < start:
            continue
        grouped.setdefault(adjustment.effective_date, []).append(adjustment)
    return grouped


def _require_member_count(active: set[str], expected: int, on_date: date) -> None:
    if len(active) != expected:
        raise ValueError(
            f"expected {expected} active members, found {len(active)} on {on_date.isoformat()}"
        )


def _intervals_from_periods(
    anchor: MembershipAnchor,
    periods: Sequence[tuple[date, date | None, frozenset[str]]],
) -> tuple[MembershipInterval, ...]:
    raw_by_symbol: dict[str, list[tuple[date, date | None]]] = {}
    for member_from, member_to, symbols in sorted(periods, key=lambda item: item[0]):
        for symbol in symbols:
            raw_by_symbol.setdefault(symbol, []).append((member_from, member_to))

    intervals: list[MembershipInterval] = []
    for symbol, raw_intervals in raw_by_symbol.items():
        merged: list[tuple[date, date | None]] = []
        for member_from, member_to in raw_intervals:
            if merged and merged[-1][1] == member_from:
                merged[-1] = (merged[-1][0], member_to)
            else:
                merged.append((member_from, member_to))
        intervals.extend(
            MembershipInterval(
                index_code=anchor.index_code,
                symbol=symbol,
                member_from=member_from,
                member_to=member_to,
                source=anchor.source,
                source_fetched_at=anchor.source_fetched_at,
            )
            for member_from, member_to in merged
        )
    return tuple(sorted(intervals, key=lambda item: (item.symbol, item.member_from)))
