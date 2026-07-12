from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Sequence


@dataclass(frozen=True)
class IndividualAShareDividendTaxPolicy:
    short_term_rate: float = 0.20
    medium_term_rate: float = 0.10
    long_term_rate: float = 0.0

    def rate(self, acquired_date: date, sale_date: date) -> float:
        if sale_date <= acquired_date:
            raise ValueError("sale_date must be after acquired_date")
        if sale_date <= _add_months(acquired_date, 1):
            return self.short_term_rate
        if sale_date <= _add_months(acquired_date, 12):
            return self.medium_term_rate
        return self.long_term_rate


@dataclass
class DividendTaxLot:
    shares: int
    acquired_date: date
    pending_dividend: float = 0.0

    def __post_init__(self) -> None:
        if self.shares <= 0:
            raise ValueError("dividend tax lot shares must be positive")
        if self.pending_dividend < 0:
            raise ValueError("pending dividend must be non-negative")


def accrue_cash_dividend(
    lots: Sequence[DividendTaxLot],
    *,
    cash_dividend_per_share: float,
) -> None:
    if cash_dividend_per_share < 0:
        raise ValueError("cash_dividend_per_share must be non-negative")
    for lot in lots:
        lot.pending_dividend = round(
            lot.pending_dividend + lot.shares * cash_dividend_per_share,
            6,
        )


def apply_share_multiplier(
    lots: Sequence[DividendTaxLot],
    *,
    share_multiplier: float,
) -> None:
    for lot in lots:
        raw_shares = lot.shares * share_multiplier
        next_shares = round(raw_shares)
        if abs(raw_shares - next_shares) > 1e-6:
            raise ValueError("share multiplier creates fractional dividend-tax lot")
        lot.shares = next_shares


def settle_dividend_tax(
    lots: list[DividendTaxLot],
    *,
    shares_sold: int,
    sale_date: date,
    policy: IndividualAShareDividendTaxPolicy,
) -> float:
    if shares_sold <= 0:
        raise ValueError("shares_sold must be positive")
    if shares_sold > sum(lot.shares for lot in lots):
        raise ValueError("shares_sold exceeds dividend-tax lots")
    remaining = shares_sold
    total_tax = 0.0
    while remaining > 0:
        lot = lots[0]
        allocated_shares = min(remaining, lot.shares)
        allocated_dividend = lot.pending_dividend * allocated_shares / lot.shares
        total_tax += allocated_dividend * policy.rate(lot.acquired_date, sale_date)
        lot.shares -= allocated_shares
        lot.pending_dividend = round(lot.pending_dividend - allocated_dividend, 6)
        remaining -= allocated_shares
        if lot.shares == 0:
            lots.pop(0)
    return round(total_tax, 6)


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)
