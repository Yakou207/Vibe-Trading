from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Iterable, Sequence

from fintech_quant.research.dataset import ResearchDataset, SupplementalRow
from fintech_quant.research.point_in_time import MembershipAsOfIndex, SupplementalAsOfIndex
from fintech_quant.research.scoring import build_stock_scores


@dataclass(frozen=True)
class DataHealthThresholds:
    expected_members: int = 300
    minimum_price_coverage: float = 0.95
    minimum_fundamental_coverage: float = 0.80
    minimum_capital_flow_coverage: float = 0.95
    fundamental_warmup_days: int = 180
    maximum_fundamental_age_days: int = 180
    maximum_capital_flow_age_sessions: int = 3


@dataclass(frozen=True)
class DataHealthIssue:
    code: str
    message: str
    observed: object
    threshold: object


@dataclass(frozen=True)
class DataHealthReport:
    passed: bool
    metrics: dict[str, object]
    issues: tuple[DataHealthIssue, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "metrics": self.metrics,
            "issues": [asdict(issue) for issue in self.issues],
        }


def validate_research_data(
    dataset: ResearchDataset,
    *,
    thresholds: DataHealthThresholds | None = None,
) -> DataHealthReport:
    active_thresholds = thresholds or DataHealthThresholds()
    _validate_thresholds(active_thresholds)
    issues: list[DataHealthIssue] = []
    trading_dates = tuple(sorted({row.trade_date for row in dataset.features}))
    if not trading_dates:
        issue = DataHealthIssue("empty_features", "No feature rows are available.", 0, 1)
        return DataHealthReport(False, {"feature_rows": 0}, (issue,))

    membership_index = MembershipAsOfIndex(dataset.membership_intervals)
    active_by_date = {
        trade_date: tuple(
            symbol
            for symbol in dataset.universe_symbols
            if membership_index.is_active(symbol, trade_date)
        )
        for trade_date in trading_dates
    }
    member_counts = {trade_date.isoformat(): len(symbols) for trade_date, symbols in active_by_date.items()}
    wrong_member_counts = {
        trade_date: count
        for trade_date, count in member_counts.items()
        if count != active_thresholds.expected_members
    }
    if wrong_member_counts:
        issues.append(
            DataHealthIssue(
                "membership_count",
                "Historical membership count differs from the required index size.",
                wrong_member_counts,
                active_thresholds.expected_members,
            )
        )

    expected_pairs = sum(active_thresholds.expected_members for _ in trading_dates)
    feature_pairs = {(row.trade_date, row.symbol) for row in dataset.features}
    price_coverage = _ratio(len(feature_pairs), expected_pairs)
    if price_coverage < active_thresholds.minimum_price_coverage:
        issues.append(
            DataHealthIssue(
                "price_coverage",
                "Price coverage is below the required member-date threshold.",
                price_coverage,
                active_thresholds.minimum_price_coverage,
            )
        )

    fundamental_index = SupplementalAsOfIndex(
        dataset.fundamentals.values(),
        trading_dates=trading_dates,
        allow_undated=False,
    )
    capital_flow_index = SupplementalAsOfIndex(
        dataset.capital_flow.values(),
        trading_dates=trading_dates,
        allow_undated=False,
    )
    warmup_start = trading_dates[0] + timedelta(days=active_thresholds.fundamental_warmup_days)
    fundamental_pairs = [
        (trade_date, symbol)
        for trade_date, symbols in active_by_date.items()
        if trade_date >= warmup_start
        for symbol in symbols
    ]
    # A price-derived flow signal is only actionable on rows where the stock has
    # a market observation. Missing member-day prices are gated separately by
    # price coverage and must not cause an old signal to be carried through a suspension.
    capital_pairs = sorted(feature_pairs)
    fundamental_rows, fundamental_stale = _available_rows(
        fundamental_index,
        fundamental_pairs,
        max_age_days=active_thresholds.maximum_fundamental_age_days,
    )
    capital_rows, capital_stale = _available_rows(
        capital_flow_index,
        capital_pairs,
        max_age_sessions=active_thresholds.maximum_capital_flow_age_sessions,
    )
    fundamental_coverage = _ratio(len(fundamental_rows), len(fundamental_pairs))
    capital_flow_coverage = _ratio(len(capital_rows), len(capital_pairs))
    if fundamental_coverage < active_thresholds.minimum_fundamental_coverage:
        issues.append(
            DataHealthIssue(
                "fundamental_coverage",
                "Fundamental coverage is below the required threshold.",
                fundamental_coverage,
                active_thresholds.minimum_fundamental_coverage,
            )
        )
    if capital_flow_coverage < active_thresholds.minimum_capital_flow_coverage:
        issues.append(
            DataHealthIssue(
                "capital_flow_coverage",
                "Capital-flow coverage is below the required threshold.",
                capital_flow_coverage,
                active_thresholds.minimum_capital_flow_coverage,
            )
        )
    if fundamental_stale:
        issues.append(
            DataHealthIssue(
                "fundamental_stale",
                "Fundamental rows exceed the maximum age.",
                fundamental_stale,
                active_thresholds.maximum_fundamental_age_days,
            )
        )
    if capital_stale:
        issues.append(
            DataHealthIssue(
                "capital_flow_stale",
                "Capital-flow rows exceed the maximum trading-session age.",
                capital_stale,
                active_thresholds.maximum_capital_flow_age_sessions,
            )
        )

    future_leakage = _future_provenance_count(
        tuple(dataset.fundamentals.values()) + tuple(dataset.capital_flow.values())
    )
    if future_leakage:
        issues.append(
            DataHealthIssue(
                "future_leakage",
                "A supplemental row claims an availability date after its indexed availability key.",
                future_leakage,
                0,
            )
        )

    scores = build_stock_scores(dataset)
    fundamental_stats = _component_stats(scores.values(), "fundamental")
    capital_stats = _component_stats(scores.values(), "capital_flow")
    if fundamental_stats["unique_count"] < 2:
        issues.append(
            DataHealthIssue(
                "fundamental_constant",
                "Fundamental component scores are constant.",
                fundamental_stats,
                {"minimum_unique_count": 2},
            )
        )
    if capital_stats["all_zero"]:
        issues.append(
            DataHealthIssue(
                "capital_flow_all_zero",
                "Capital-flow component scores are all zero.",
                capital_stats,
                {"all_zero": False},
            )
        )
    elif capital_stats["unique_count"] < 2:
        issues.append(
            DataHealthIssue(
                "capital_flow_constant",
                "Capital-flow component scores are constant.",
                capital_stats,
                {"minimum_unique_count": 2},
            )
        )

    metrics: dict[str, object] = {
        "feature_rows": len(dataset.features),
        "trading_dates": len(trading_dates),
        "member_counts": member_counts,
        "price_coverage": price_coverage,
        "fundamental_coverage": fundamental_coverage,
        "capital_flow_coverage": capital_flow_coverage,
        "fundamental_stale_count": fundamental_stale,
        "capital_flow_stale_count": capital_stale,
        "future_leakage_count": future_leakage,
        "fundamental_field_coverage": _field_coverage(
            fundamental_rows,
            ("pe", "pb", "roe", "growth"),
        ),
        "capital_flow_field_coverage": _field_coverage(
            capital_rows,
            (
                "main_net_inflow",
                "main_outflow_days",
                "margin_financing_positive",
                "price_volume_flow_signal",
                "price_volume_outflow_days",
            ),
        ),
        "capital_flow_mode_counts": _capital_flow_mode_counts(capital_rows),
        "fundamental_score": fundamental_stats,
        "capital_flow_score": capital_stats,
    }
    return DataHealthReport(not issues, metrics, tuple(issues))


def _capital_flow_mode_counts(rows: Sequence[SupplementalRow]) -> dict[str, int]:
    counts = {"price_volume_proxy": 0, "real_main_flow": 0, "unknown": 0}
    for row in rows:
        if row.values.get("flow_proxy_kind") == "price_volume_cmf_obv":
            counts["price_volume_proxy"] += 1
        elif row.values.get("main_net_inflow") is not None:
            counts["real_main_flow"] += 1
        else:
            counts["unknown"] += 1
    return counts


def _available_rows(
    index: SupplementalAsOfIndex,
    pairs: Sequence[tuple[date, str]],
    *,
    max_age_days: int | None = None,
    max_age_sessions: int | None = None,
) -> tuple[list[SupplementalRow], int]:
    rows: list[SupplementalRow] = []
    stale = 0
    for signal_date, symbol in pairs:
        latest = index.lookup(symbol, signal_date)
        available = index.lookup(
            symbol,
            signal_date,
            max_age_days=max_age_days,
            max_age_sessions=max_age_sessions,
        )
        if available is not None:
            rows.append(available)
        elif latest is not None:
            stale += 1
    return rows, stale


def _future_provenance_count(rows: Iterable[SupplementalRow]) -> int:
    count = 0
    for row in rows:
        raw_available = row.values.get("available_date")
        if isinstance(raw_available, str):
            raw_available = date.fromisoformat(raw_available)
        if isinstance(raw_available, date) and row.trade_date is not None and raw_available > row.trade_date:
            count += 1
    return count


def _component_stats(scores: Iterable[object], component_name: str) -> dict[str, object]:
    values = [float(score.components[component_name].score) for score in scores]  # type: ignore[attr-defined]
    if not values:
        return {"minimum": 0.0, "maximum": 0.0, "unique_count": 0, "stddev": 0.0, "all_zero": True}
    return {
        "minimum": min(values),
        "maximum": max(values),
        "unique_count": len(set(values)),
        "stddev": round(statistics.pstdev(values), 6),
        "all_zero": all(value == 0 for value in values),
    }


def _field_coverage(rows: Sequence[SupplementalRow], fields: Sequence[str]) -> dict[str, float]:
    return {
        field: _ratio(sum(1 for row in rows if row.values.get(field) is not None), len(rows))
        for field in fields
    }


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _validate_thresholds(thresholds: DataHealthThresholds) -> None:
    if thresholds.expected_members <= 0:
        raise ValueError("expected_members must be positive")
    for name in (
        "minimum_price_coverage",
        "minimum_fundamental_coverage",
        "minimum_capital_flow_coverage",
    ):
        value = getattr(thresholds, name)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"{name} must be between 0 and 1")
