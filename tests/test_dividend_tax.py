from __future__ import annotations

from datetime import date


def test_individual_a_share_dividend_tax_rate_respects_holding_boundaries() -> None:
    from fintech_quant.backtesting.dividend_tax import IndividualAShareDividendTaxPolicy

    policy = IndividualAShareDividendTaxPolicy()
    acquired = date(2025, 1, 31)

    assert policy.rate(acquired, date(2025, 2, 28)) == 0.20
    assert policy.rate(acquired, date(2025, 3, 1)) == 0.10
    assert policy.rate(acquired, date(2026, 1, 31)) == 0.10
    assert policy.rate(acquired, date(2026, 2, 1)) == 0.0


def test_dividend_tax_lots_settle_fifo_tax_when_shares_are_sold() -> None:
    from fintech_quant.backtesting.dividend_tax import (
        DividendTaxLot,
        IndividualAShareDividendTaxPolicy,
        accrue_cash_dividend,
        settle_dividend_tax,
    )

    lots = [
        DividendTaxLot(600, date(2025, 1, 1)),
        DividendTaxLot(400, date(2025, 12, 20)),
    ]
    accrue_cash_dividend(lots, cash_dividend_per_share=1.0)

    tax = settle_dividend_tax(
        lots,
        shares_sold=800,
        sale_date=date(2026, 1, 15),
        policy=IndividualAShareDividendTaxPolicy(),
    )

    assert tax == 40.0
    assert [(lot.shares, lot.pending_dividend) for lot in lots] == [(200, 200.0)]
