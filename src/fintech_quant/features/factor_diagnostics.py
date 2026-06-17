from __future__ import annotations

import pandas as pd

from fintech_quant.features.factor_library import FactorSpec


def factor_diagnostics(
    features: pd.DataFrame,
    factor_columns: list[str],
    target_column: str = "target_next_return_1d",
    factor_specs: list[FactorSpec] | None = None,
) -> dict[str, dict[str, float]]:
    diagnostics: dict[str, dict[str, float]] = {}
    spec_by_name = {spec.name: spec for spec in factor_specs or []}
    for column in factor_columns:
        if column not in features.columns or target_column not in features.columns:
            continue
        data = features[[column, target_column]].apply(pd.to_numeric, errors="coerce").dropna()
        if data.empty:
            metrics = {"ic": 0.0, "rank_ic": 0.0, "coverage": 0.0}
            diagnostics[column] = _with_metadata(column, metrics, spec_by_name)
            continue
        ic = _safe_corr(data[column], data[target_column], method="pearson")
        rank_ic = _safe_corr(data[column].rank(), data[target_column].rank(), method="pearson")
        diagnostics[column] = {
            **_with_metadata(
                column,
                {
                    "ic": ic,
                    "rank_ic": rank_ic,
                    "coverage": round(len(data) / len(features), 10),
                },
                spec_by_name,
            ),
        }
    return diagnostics


def _with_metadata(
    column: str,
    metrics: dict[str, float],
    spec_by_name: dict[str, FactorSpec],
) -> dict[str, object]:
    spec = spec_by_name.get(column)
    ic = float(metrics.get("ic", 0.0))
    return {
        **metrics,
        "group": spec.group if spec else "unclassified",
        "description": spec.description if spec else column,
        "direction": _direction(ic),
    }


def _direction(ic: float) -> str:
    if ic > 0:
        return "positive"
    if ic < 0:
        return "negative"
    return "neutral"


def _safe_corr(left: pd.Series, right: pd.Series, method: str) -> float:
    value = left.corr(right, method=method)
    if pd.isna(value):
        return 0.0
    return round(float(value), 10)
