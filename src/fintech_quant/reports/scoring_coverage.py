from __future__ import annotations

from collections.abc import Mapping, Sequence

from fintech_quant.features import StockScore, factor_pipeline_name


def build_scoring_coverage_report(
    scores: Mapping[tuple[object, str], StockScore],
) -> dict[str, object]:
    score_values = list(scores.values())
    row_count = len(score_values)
    component_names = sorted({name for score in score_values for name in score.components})
    missing_counts: dict[str, int] = {}
    for score in score_values:
        for field in score.missing_fields:
            missing_counts[field] = missing_counts.get(field, 0) + 1

    return {
        "pipeline": factor_pipeline_name(),
        "row_count": row_count,
        "score_distribution": _distribution([score.total for score in score_values]),
        "confidence_average": _average([score.confidence for score in score_values]),
        "component_summary": {
            name: _component_summary(name, score_values) for name in component_names
        },
        "missing_field_counts": dict(sorted(missing_counts.items())),
        "missing_field_rates": {
            field: round(count / row_count, 4) if row_count else 0.0
            for field, count in sorted(missing_counts.items())
        },
    }


def _component_summary(name: str, scores: Sequence[StockScore]) -> dict[str, object]:
    components = [score.components[name] for score in scores if name in score.components]
    values = [component.score for component in components]
    max_score = components[0].max_score if components else 0.0
    return {
        "max_score": max_score,
        "average_score": _average(values),
        "min_score": min(values) if values else 0.0,
        "max_score_observed": max(values) if values else 0.0,
        "full_score_count": sum(1 for value in values if value == max_score),
    }


def _distribution(values: Sequence[float]) -> dict[str, float]:
    if not values:
        return {"average": 0.0, "min": 0.0, "max": 0.0}
    return {"average": _average(values), "min": min(values), "max": max(values)}


def _average(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0
