from __future__ import annotations

from datetime import date

import pytest


def test_daily_decision_report_contains_only_requested_date_scores_and_static_risk() -> None:
    from fintech_quant.research.daily_decision import build_daily_decision_report

    report = build_daily_decision_report(
        _dataset(),
        as_of=date(2026, 1, 5),
        data_health=_health(passed=True),
        expected_members=2,
        input_refs={"features": {"sha256": "abc"}},
    )

    assert report["as_of"] == "2026-01-05"
    assert report["data_health_passed"] is True
    assert report["active_member_count"] == 2
    assert {row["trade_date"] for row in report["scores"]} == {"2026-01-05"}
    assert {row["symbol"] for row in report["scores"]} == {"000001.SZ", "600000.SH"}
    assert {warning["rule"] for warning in report["risk_warnings"]} == {
        "broad_market_drop_gt_3pct_count"
    }
    assert report["risk_summary"]["by_action"] == {"reduce": 2}
    assert report["inputs"] == {"features": {"sha256": "abc"}}


def test_daily_decision_report_rejects_stale_feature_date() -> None:
    from fintech_quant.research.daily_decision import build_daily_decision_report

    with pytest.raises(ValueError, match="latest feature date 2026-01-05 does not match as_of"):
        build_daily_decision_report(
            _dataset(),
            as_of=date(2026, 1, 6),
            data_health=_health(passed=True),
            expected_members=2,
        )


def test_daily_decision_report_rejects_failed_data_health() -> None:
    from fintech_quant.research.daily_decision import build_daily_decision_report

    with pytest.raises(ValueError, match="data health did not pass"):
        build_daily_decision_report(
            _dataset(),
            as_of=date(2026, 1, 5),
            data_health=_health(passed=False),
            expected_members=2,
        )


def test_daily_decision_report_requires_fresh_benchmark_row() -> None:
    from fintech_quant.research.daily_decision import build_daily_decision_report

    dataset = _dataset()
    dataset.market_state[date(2026, 1, 5)].values.pop("index_close")

    with pytest.raises(ValueError, match="benchmark row is missing index_close"):
        build_daily_decision_report(
            dataset,
            as_of=date(2026, 1, 5),
            data_health=_health(passed=True),
            expected_members=2,
        )


def test_daily_decision_report_reports_confirmed_suspension_without_scoring_it() -> None:
    from fintech_quant.research.daily_decision import build_daily_decision_report

    dataset = _dataset()
    dataset.features[:] = [
        row
        for row in dataset.features
        if not (row.symbol == "600000.SH" and row.trade_date == date(2026, 1, 5))
    ]

    report = build_daily_decision_report(
        dataset,
        as_of=date(2026, 1, 5),
        data_health=_health(passed=True),
        expected_members=2,
        suspended_members={"600000.SH": date(2026, 1, 2)},
    )

    assert report["active_member_count"] == 2
    assert report["tradable_member_count"] == 1
    assert report["suspended_members"] == [
        {"symbol": "600000.SH", "last_trade_date": "2026-01-02"}
    ]
    assert {row["symbol"] for row in report["scores"]} == {"000001.SZ"}


def test_daily_decision_report_rejects_unexplained_missing_member() -> None:
    from fintech_quant.research.daily_decision import build_daily_decision_report

    dataset = _dataset()
    dataset.features[:] = [
        row
        for row in dataset.features
        if not (row.symbol == "600000.SH" and row.trade_date == date(2026, 1, 5))
    ]

    with pytest.raises(ValueError, match="plus suspended 0 does not match expected 2"):
        build_daily_decision_report(
            dataset,
            as_of=date(2026, 1, 5),
            data_health=_health(passed=True),
            expected_members=2,
        )


def test_daily_decision_report_caps_suspended_members() -> None:
    from fintech_quant.research.daily_decision import build_daily_decision_report

    with pytest.raises(ValueError, match="suspended member count 1 exceeds maximum 0"):
        build_daily_decision_report(
            _dataset(),
            as_of=date(2026, 1, 5),
            data_health=_health(passed=True),
            expected_members=2,
            suspended_members={"600000.SH": date(2026, 1, 2)},
            max_suspended_members=0,
        )


def test_daily_decision_report_rejects_suspended_member_with_current_row() -> None:
    from fintech_quant.research.daily_decision import build_daily_decision_report

    with pytest.raises(ValueError, match="must not have a current feature row"):
        build_daily_decision_report(
            _dataset(),
            as_of=date(2026, 1, 5),
            data_health=_health(passed=True),
            expected_members=2,
            suspended_members={"600000.SH": date(2026, 1, 2)},
        )


def _dataset():
    from fintech_quant.research.dataset import (
        FeatureRow,
        MarketStateRow,
        ResearchDataset,
        SupplementalRow,
    )

    symbols = ("000001.SZ", "600000.SH")
    previous = date(2026, 1, 2)
    current = date(2026, 1, 5)
    features = [
        FeatureRow(symbol, trade_date, _feature_values(close=10.0, trade_date=trade_date))
        for trade_date in (previous, current)
        for symbol in symbols
    ]
    fundamentals = {
        (symbol, current): SupplementalRow(
            symbol,
            current,
            {
                "available_date": current,
                "pe": 10.0,
                "pb": 1.0,
                "roe": 0.15,
                "growth": 0.1,
            },
        )
        for symbol in symbols
    }
    capital_flow = {
        (symbol, current): SupplementalRow(
            symbol,
            current,
            {
                "available_date": current,
                "flow_proxy_kind": "price_volume_cmf_obv",
                "price_volume_flow_signal": 0.1,
                "price_volume_outflow_days": 0,
            },
        )
        for symbol in symbols
    }
    market_state = {
        current: MarketStateRow(
            current,
            {
                "index_close": 4000.0,
                "index_ma250": 3900.0,
                "index_below_annual_ma": False,
                "broad_market_drop_gt_3pct_count": 16,
            },
        )
    }
    return ResearchDataset(
        features=features,
        fundamentals=fundamentals,
        capital_flow=capital_flow,
        market_state=market_state,
        information_records=[],
        universe_symbols=symbols,
        require_point_in_time=True,
    )


def _feature_values(*, close: float, trade_date: date) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "close": close,
        "open": close,
        "high": close,
        "low": close,
        "volume": 1000.0,
        "return_1d": 0.01,
        "close_above_ma20": True,
        "close_above_ma60": True,
        "rs_rank_20d": 0.8,
        "rsi14": 55.0,
        "macd_positive": True,
        "limit_up_streak": 0,
    }


def _health(*, passed: bool):
    from fintech_quant.research.data_health import DataHealthIssue, DataHealthReport

    issues = () if passed else (DataHealthIssue("fixture", "failed", 0, 1),)
    return DataHealthReport(passed=passed, metrics={"fixture": True}, issues=issues)
