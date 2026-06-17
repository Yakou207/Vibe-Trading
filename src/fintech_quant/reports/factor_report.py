from __future__ import annotations


def build_factor_report(diagnostics: dict[str, dict[str, float]]) -> dict[str, object]:
    return {
        "report": "factor_diagnostics",
        "factor_count": len(diagnostics),
        "factors": diagnostics,
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
