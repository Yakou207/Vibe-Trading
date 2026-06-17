from __future__ import annotations


def build_factor_report(diagnostics: dict[str, dict[str, float]]) -> dict[str, object]:
    return {
        "report": "factor_diagnostics",
        "factor_count": len(diagnostics),
        "factors": diagnostics,
        "top_abs_ic": _top_abs_ic(diagnostics),
        "top_rank_ic": _top_rank_ic(diagnostics),
        "warnings": _warnings(diagnostics),
    }


def _warnings(diagnostics: dict[str, dict[str, float]]) -> list[str]:
    warnings = []
    low_coverage = [
        factor
        for factor, metrics in diagnostics.items()
        if metrics.get("coverage", 0.0) < 0.8
    ]
    if low_coverage:
        warnings.append(f"Low coverage factors: {', '.join(low_coverage)}")
    return warnings


def _top_abs_ic(diagnostics: dict[str, dict[str, float]], limit: int = 10) -> list[dict[str, object]]:
    rows = [
        {
            "factor": factor,
            "ic": metrics.get("ic", 0.0),
            "rank_ic": metrics.get("rank_ic", 0.0),
            "coverage": metrics.get("coverage", 0.0),
            "group": metrics.get("group", "unclassified"),
        }
        for factor, metrics in diagnostics.items()
    ]
    return sorted(rows, key=lambda row: abs(float(row["ic"])), reverse=True)[:limit]


def _top_rank_ic(diagnostics: dict[str, dict[str, float]], limit: int = 10) -> list[dict[str, object]]:
    rows = [
        {
            "factor": factor,
            "ic": metrics.get("ic", 0.0),
            "rank_ic": metrics.get("rank_ic", 0.0),
            "coverage": metrics.get("coverage", 0.0),
            "group": metrics.get("group", "unclassified"),
        }
        for factor, metrics in diagnostics.items()
    ]
    return sorted(rows, key=lambda row: abs(float(row["rank_ic"])), reverse=True)[:limit]
