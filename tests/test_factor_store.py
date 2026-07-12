from __future__ import annotations

from datetime import date


def test_financial_indicator_uses_matching_statement_availability() -> None:
    from fintech_quant.data.factor_store import materialize_fundamentals

    rows = materialize_fundamentals(
        [
            _valuation_record("2023-04-01", pe=20.0, pb=1.8),
            _financial_indicator_record("2023-03-31", roe=0.16, growth=0.12),
            _statement_record("2023-03-31", "2023-04-24"),
            _valuation_record("2023-04-25", pe=18.0, pb=1.5),
        ],
        source_fetched_at="2026-07-10T12:00:00+08:00",
    )

    by_date = {row.available_date: row for row in rows}
    assert by_date[date(2023, 4, 1)].values == {
        "pe": 20.0,
        "pb": 1.8,
        "roe": None,
        "growth": None,
        "goodwill_ratio": None,
    }
    assert by_date[date(2023, 4, 24)].values["roe"] == 0.16
    assert by_date[date(2023, 4, 24)].values["growth"] == 0.12
    assert by_date[date(2023, 4, 24)].report_period == date(2023, 3, 31)
    assert by_date[date(2023, 4, 25)].values["pe"] == 18.0
    assert by_date[date(2023, 4, 25)].values["roe"] == 0.16


def test_unmatched_financial_indicator_is_not_materialized() -> None:
    from fintech_quant.data.factor_store import materialize_fundamentals

    rows = materialize_fundamentals(
        [_financial_indicator_record("2023-03-31", roe=0.16, growth=0.12)],
        source_fetched_at="2026-07-10T12:00:00+08:00",
    )

    assert rows == []


def test_verified_statements_derive_annualized_roe_and_same_period_revenue_growth() -> None:
    from fintech_quant.data.factor_store import materialize_fundamentals

    rows = materialize_fundamentals(
        [
            _statement_value_record(
                "2022-03-31",
                "2022-04-20",
                "利润表",
                "revenue=100; net_profit=10",
            ),
            _statement_value_record(
                "2023-03-31",
                "2023-04-24",
                "资产负债表",
                "goodwill=0; total_assets=1000; total_liabilities=400",
            ),
            _statement_value_record(
                "2023-03-31",
                "2023-04-25",
                "利润表",
                "revenue=120; net_profit=18",
            ),
        ],
        source_fetched_at="2026-07-10T12:00:00+08:00",
    )

    current = next(row for row in rows if row.report_period == date(2023, 3, 31))
    assert current.available_date == date(2023, 4, 25)
    assert current.values["roe"] == 0.12
    assert current.values["growth"] == 0.20


def test_statement_growth_does_not_use_a_comparator_published_later() -> None:
    from fintech_quant.data.factor_store import materialize_fundamentals

    rows = materialize_fundamentals(
        [
            _statement_value_record(
                "2022-03-31",
                "2024-04-20",
                "利润表",
                "revenue=100; net_profit=10",
            ),
            _statement_value_record(
                "2023-03-31",
                "2023-04-25",
                "利润表",
                "revenue=120; net_profit=18",
            ),
        ],
        source_fetched_at="2026-07-10T12:00:00+08:00",
    )

    current = next(row for row in rows if row.report_period == date(2023, 3, 31))
    assert current.values["growth"] is None


def test_statement_roe_prefers_trailing_twelve_month_profit_and_average_equity() -> None:
    from fintech_quant.data.factor_store import materialize_fundamentals

    rows = materialize_fundamentals(
        [
            _statement_value_record(
                "2022-03-31",
                "2022-04-20",
                "资产负债表",
                "total_assets=900; total_liabilities=400",
            ),
            _statement_value_record(
                "2022-03-31",
                "2022-04-20",
                "利润表",
                "revenue=100; net_profit=10",
            ),
            _statement_value_record(
                "2022-12-31",
                "2023-04-20",
                "利润表",
                "revenue=500; net_profit=50",
            ),
            _statement_value_record(
                "2023-03-31",
                "2023-04-25",
                "资产负债表",
                "total_assets=1000; total_liabilities=400",
            ),
            _statement_value_record(
                "2023-03-31",
                "2023-04-25",
                "利润表",
                "revenue=120; net_profit=18",
            ),
        ],
        source_fetched_at="2026-07-10T12:00:00+08:00",
    )

    current = next(row for row in rows if row.report_period == date(2023, 3, 31))
    assert current.values["roe"] == 0.105455


def test_missing_flow_day_does_not_reset_or_extend_outflow_streak() -> None:
    from fintech_quant.data.factor_store import materialize_capital_flow

    rows = materialize_capital_flow(
        [
            _flow_record("2026-01-02", -10.0),
            _flow_record("2026-01-06", -20.0),
        ],
        trading_dates=(date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 6)),
        source_fetched_at="2026-07-10T12:00:00+08:00",
    )

    assert rows[0].values["main_outflow_days"] == 1
    assert rows[1].values["main_outflow_days"] is None


def _valuation_record(available_date: str, *, pe: float, pb: float):
    from fintech_quant.information import InformationCategory, InformationRecord

    return InformationRecord(
        symbol="000001.SZ",
        sector=None,
        published_at=date.fromisoformat(available_date),
        source="akshare_fundamental",
        category=InformationCategory.STOCK_DATA,
        title=f"valuation {available_date}",
        url="",
        summary=f"pe={pe}; pb={pb}",
        risk_tags=("selected_universe", "fundamental", "valuation"),
        metadata={"record_kind": "valuation", "available_date_source": "row_date"},
    )


def _financial_indicator_record(report_period: str, *, roe: float, growth: float):
    from fintech_quant.information import InformationCategory, InformationRecord

    return InformationRecord(
        symbol="000001.SZ",
        sector=None,
        published_at=date.fromisoformat(report_period),
        source="akshare_fundamental",
        category=InformationCategory.STOCK_DATA,
        title=f"financial {report_period}",
        url="",
        summary=f"roe={roe}; growth={growth}",
        risk_tags=("selected_universe", "financial_indicator", "unverified_availability"),
        metadata={
            "record_kind": "financial_indicator",
            "report_period": report_period,
            "availability_verified": False,
        },
    )


def _statement_record(report_period: str, available_date: str):
    from fintech_quant.information import InformationCategory, InformationRecord

    return InformationRecord(
        symbol="000001.SZ",
        sector=None,
        published_at=date.fromisoformat(available_date),
        source="akshare_financial_statement",
        category=InformationCategory.STOCK_DATA,
        title=f"statement {report_period}",
        url="",
        summary="goodwill=100; total_assets=1000",
        risk_tags=("selected_universe", "financial_statement", "balance_sheet"),
        metadata={
            "statement_type": "资产负债表",
            "report_period": report_period,
            "available_date_source": "更新日期",
        },
    )


def _statement_value_record(
    report_period: str,
    available_date: str,
    statement_type: str,
    summary: str,
):
    from fintech_quant.information import InformationCategory, InformationRecord

    return InformationRecord(
        symbol="000001.SZ",
        sector=None,
        published_at=date.fromisoformat(available_date),
        source="akshare_financial_statement",
        category=InformationCategory.STOCK_DATA,
        title=f"{statement_type} {report_period}",
        url="",
        summary=summary,
        risk_tags=("selected_universe", "financial_statement"),
        metadata={
            "statement_type": statement_type,
            "report_period": report_period,
            "available_date_source": "更新日期",
        },
    )


def _flow_record(trade_date: str, main_net_inflow: float):
    from fintech_quant.information import InformationCategory, InformationRecord

    return InformationRecord(
        symbol="000001.SZ",
        sector=None,
        published_at=date.fromisoformat(trade_date),
        source="akshare_fund_flow",
        category=InformationCategory.STOCK_DATA,
        title=f"flow {trade_date}",
        url="",
        summary=f"main_net_inflow={main_net_inflow}",
        risk_tags=("selected_universe", "capital_flow"),
    )
