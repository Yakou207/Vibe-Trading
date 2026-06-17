from __future__ import annotations

import pandas as pd


def factor_diagnostics(
    features: pd.DataFrame,
    factor_columns: list[str],
    target_column: str = "target_next_return_1d",
) -> dict[str, dict[str, float]]:
    diagnostics: dict[str, dict[str, float]] = {}
    for column in factor_columns:
        data = features[[column, target_column]].apply(pd.to_numeric, errors="coerce").dropna()
        if data.empty:
            diagnostics[column] = {"ic": 0.0, "rank_ic": 0.0, "coverage": 0.0}
            continue
        diagnostics[column] = {
            "ic": _safe_corr(data[column], data[target_column], method="pearson"),
            "rank_ic": _safe_corr(data[column], data[target_column], method="spearman"),
            "coverage": round(len(data) / len(features), 10),
        }
    return diagnostics


def _safe_corr(left: pd.Series, right: pd.Series, method: str) -> float:
    value = left.corr(right, method=method)
    if pd.isna(value):
        return 0.0
    return round(float(value), 10)
