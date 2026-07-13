from __future__ import annotations

from datetime import date
from typing import Mapping

from fintech_quant.features import StockScore
from fintech_quant.research.data_health import DataHealthReport
from fintech_quant.research.dataset import FeatureRow, ResearchDataset, SupplementalRow
from fintech_quant.research.point_in_time import SupplementalAsOfIndex
from fintech_quant.research.risk_builder import PortfolioRiskState, build_risk_input
from fintech_quant.research.scoring import build_stock_scores
from fintech_quant.risk import RiskLimits, evaluate_risk


def build_daily_decision_report(
    dataset: ResearchDataset,
    *,
    as_of: date,
    data_health: DataHealthReport,
    expected_members: int = 300,
    input_refs: Mapping[str, object] | None = None,
    limits: RiskLimits | None = None,
) -> dict[str, object]:
    if not data_health.passed:
        raise ValueError("data health did not pass")
    if expected_members <= 0:
        raise ValueError("expected_members must be positive")
    feature_dates = tuple(sorted({row.trade_date for row in dataset.features}))
    if not feature_dates:
        raise ValueError("daily decision dataset has no feature rows")
    latest_feature_date = feature_dates[-1]
    if latest_feature_date != as_of:
        raise ValueError(
            f"latest feature date {latest_feature_date.isoformat()} does not match "
            f"as_of {as_of.isoformat()}"
        )
    market_state = dataset.market_state.get(as_of)
    if market_state is None:
        raise ValueError(f"benchmark row is missing for {as_of.isoformat()}")
    if market_state.values.get("index_close") is None:
        raise ValueError(f"benchmark row is missing index_close for {as_of.isoformat()}")
    current_features = [row for row in dataset.features if row.trade_date == as_of]
    active_symbols = {row.symbol for row in current_features}
    if len(active_symbols) != expected_members:
        raise ValueError(
            f"active feature member count {len(active_symbols)} does not match "
            f"expected {expected_members}"
        )

    scores = build_stock_scores(dataset)
    score_rows = [
        _score_to_json(trade_date, symbol, score)
        for (trade_date, symbol), score in sorted(scores.items())
        if trade_date == as_of
    ]
    active_limits = limits or RiskLimits(max_portfolio_drawdown=0.10)
    risk_warnings = _static_risk_warnings(
        dataset,
        current_features=current_features,
        as_of=as_of,
        limits=active_limits,
        trading_dates=feature_dates,
    )
    return {
        "as_of": as_of.isoformat(),
        "date_range": [feature_dates[0].isoformat(), feature_dates[-1].isoformat()],
        "expected_members": expected_members,
        "active_member_count": len(active_symbols),
        "data_health_passed": True,
        "data_health": data_health.to_json(),
        "inputs": dict(input_refs or {}),
        "risk_limits": _risk_limits_to_json(active_limits),
        "scores": score_rows,
        "risk_warnings": risk_warnings,
        "risk_summary": _risk_summary(risk_warnings),
    }


def _static_risk_warnings(
    dataset: ResearchDataset,
    *,
    current_features: list[FeatureRow],
    as_of: date,
    limits: RiskLimits,
    trading_dates: tuple[date, ...],
) -> list[dict[str, object]]:
    fundamentals = SupplementalAsOfIndex(
        dataset.fundamentals.values(),
        trading_dates=trading_dates,
        allow_undated=not dataset.require_point_in_time,
    )
    capital_flow = SupplementalAsOfIndex(
        dataset.capital_flow.values(),
        trading_dates=trading_dates,
        allow_undated=not dataset.require_point_in_time,
    )
    neutral = PortfolioRiskState(equity=1.0, rolling_peak=1.0, positions={})
    market_values = dataset.market_state[as_of].values
    result: list[dict[str, object]] = []
    for row in current_features:
        fundamental_row = fundamentals.lookup(row.symbol, as_of, max_age_days=180)
        capital_row = capital_flow.lookup(row.symbol, as_of, max_age_sessions=3)
        evaluation = evaluate_risk(
            build_risk_input(
                row.symbol,
                as_of,
                float(row.values["close"]),
                neutral,
                fundamentals=_values(fundamental_row),
                capital_flow=_values(capital_row),
                market_state=market_values,
                sector=_text_or_none(row.values.get("sector")),
                information_records=dataset.information_records,
            ),
            limits,
        )
        result.extend(
            {
                "trade_date": as_of.isoformat(),
                "symbol": row.symbol,
                "layer": warning.layer,
                "rule": warning.rule,
                "action": warning.action.value,
                "message": warning.message,
                "observed_value": warning.observed_value,
                "threshold_value": warning.threshold_value,
            }
            for warning in evaluation.warnings
        )
    return result


def _values(row: SupplementalRow | None) -> Mapping[str, object] | None:
    return row.values if row is not None else None


def _score_to_json(trade_date: date, symbol: str, score: StockScore) -> dict[str, object]:
    return {
        "trade_date": trade_date.isoformat(),
        "symbol": symbol,
        "total": score.total,
        "confidence": score.confidence,
        "missing_fields": list(score.missing_fields),
        "components": {
            name: {
                "score": component.score,
                "max_score": component.max_score,
                "reasons": list(component.reasons),
            }
            for name, component in sorted(score.components.items())
        },
    }


def _risk_limits_to_json(limits: RiskLimits) -> dict[str, float | int]:
    return {
        "max_position_weight": limits.max_position_weight,
        "max_portfolio_drawdown": limits.max_portfolio_drawdown,
        "max_single_position_drawdown": limits.max_single_position_drawdown,
        "max_goodwill_ratio": limits.max_goodwill_ratio,
        "max_pledge_ratio": limits.max_pledge_ratio,
        "max_main_outflow_days": limits.max_main_outflow_days,
        "broad_market_drop_threshold": limits.broad_market_drop_threshold,
    }


def _risk_summary(warnings: list[dict[str, object]]) -> dict[str, object]:
    return {
        "total_warnings": len(warnings),
        "by_layer": _count_by(warnings, "layer"),
        "by_action": _count_by(warnings, "action"),
        "by_rule": _count_by(warnings, "rule"),
    }


def _count_by(rows: list[dict[str, object]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row[field])
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _text_or_none(value: object) -> str | None:
    return None if value in (None, "") else str(value)
