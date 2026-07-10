from __future__ import annotations

from datetime import date

import pytest


@pytest.mark.parametrize(
    ("broken_fixture", "expected_code"),
    [
        ("missing_members", "membership_count"),
        ("low_price_coverage", "price_coverage"),
        ("constant_fundamental", "fundamental_constant"),
        ("zero_capital_flow", "capital_flow_all_zero"),
        ("stale_fundamental", "fundamental_stale"),
        ("future_available_date", "future_leakage"),
    ],
)
def test_required_health_failures(broken_fixture: str, expected_code: str) -> None:
    from fintech_quant.research.data_health import validate_research_data

    report = validate_research_data(
        _dataset(broken_fixture),
        thresholds=_fixture_thresholds(),
    )

    assert report.passed is False
    assert expected_code in {issue.code for issue in report.issues}


def test_healthy_point_in_time_dataset_passes_required_gates() -> None:
    from fintech_quant.research.data_health import validate_research_data

    report = validate_research_data(_dataset("healthy"), thresholds=_fixture_thresholds())

    assert report.passed is True
    assert report.issues == ()
    assert report.metrics["price_coverage"] == 1.0
    assert report.metrics["fundamental_coverage"] == 1.0
    assert report.metrics["capital_flow_coverage"] == 1.0


def _fixture_thresholds():
    from fintech_quant.research.data_health import DataHealthThresholds

    return DataHealthThresholds(
        expected_members=2,
        minimum_price_coverage=0.95,
        minimum_fundamental_coverage=0.80,
        minimum_capital_flow_coverage=0.95,
        fundamental_warmup_days=0,
        maximum_fundamental_age_days=180,
        maximum_capital_flow_age_sessions=3,
    )


def _dataset(mode: str):
    from fintech_quant.data.historical_universe import MembershipInterval
    from fintech_quant.research.dataset import FeatureRow, ResearchDataset, SupplementalRow

    trading_dates = (date(2026, 1, 2), date(2026, 1, 5))
    symbols = ("000001.SZ", "600000.SH")
    memberships = tuple(
        MembershipInterval(
            "000300",
            symbol,
            date(2025, 1, 1),
            None,
            "csindex",
            "2026-07-10T12:00:00+08:00",
        )
        for symbol in (symbols[:1] if mode == "missing_members" else symbols)
    )
    feature_symbols = symbols[:1] if mode == "low_price_coverage" else symbols
    features = [
        FeatureRow(symbol, trade_date, _feature_values(symbol, trade_date))
        for trade_date in trading_dates
        for symbol in feature_symbols
    ]

    fundamental_date = date(2025, 1, 1) if mode == "stale_fundamental" else date(2026, 1, 1)
    fundamentals = {}
    for index, symbol in enumerate(symbols):
        values = (
            {"pe": 18.0, "pb": 1.5, "roe": 0.16, "growth": 0.12}
            if mode == "constant_fundamental" or index == 0
            else {"pe": 80.0, "pb": 8.0, "roe": 0.01, "growth": -0.10}
        )
        values["available_date"] = (
            date(2026, 2, 1) if mode == "future_available_date" and index == 0 else fundamental_date
        )
        fundamentals[(symbol, fundamental_date)] = SupplementalRow(
            symbol,
            fundamental_date,
            values,
        )

    capital_flow = {}
    for trade_date in trading_dates:
        for index, symbol in enumerate(symbols):
            values = (
                {
                    "main_net_inflow": -100.0,
                    "main_outflow_days": 5,
                    "margin_financing_positive": False,
                }
                if mode == "zero_capital_flow" or index == 1
                else {
                    "main_net_inflow": 100.0,
                    "main_outflow_days": 0,
                    "margin_financing_positive": True,
                }
            )
            values["available_date"] = trade_date
            capital_flow[(symbol, trade_date)] = SupplementalRow(symbol, trade_date, values)

    return ResearchDataset(
        features=features,
        fundamentals=fundamentals,
        capital_flow=capital_flow,
        market_state={},
        information_records=[],
        universe_symbols=symbols,
        membership_intervals=memberships,
        require_point_in_time=True,
    )


def _feature_values(symbol: str, trade_date: date) -> dict[str, object]:
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "open": 10.0,
        "high": 10.0,
        "low": 10.0,
        "close": 10.0,
        "volume": 1000.0,
        "amount": 10000.0,
        "source": "fixture",
        "return_1d": 0.01,
        "close_above_ma20": True,
        "close_above_ma60": True,
        "rs_rank_20d": 0.8,
        "rsi14": 55.0,
        "macd_positive": True,
    }
