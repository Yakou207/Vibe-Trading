from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.features import StockScore, factor_pipeline_name  # noqa: E402
from fintech_quant.research.dataset import load_research_dataset  # noqa: E402
from fintech_quant.research.scoring import build_stock_scores  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize multi-factor scoring coverage and missing inputs.")
    parser.add_argument("--features", required=True)
    parser.add_argument("--universe", required=True)
    parser.add_argument("--information", default=None)
    parser.add_argument("--fundamentals", default=None)
    parser.add_argument("--capital-flow", default=None)
    parser.add_argument("--market-state", default=None)
    parser.add_argument("--output", default="outputs/scoring_coverage.json")
    args = parser.parse_args()

    dataset = load_research_dataset(
        Path(args.features),
        Path(args.universe),
        fundamentals_path=_optional_path(args.fundamentals),
        capital_flow_path=_optional_path(args.capital_flow),
        market_state_path=_optional_path(args.market_state),
        information_path=_optional_path(args.information),
    )
    scores = build_stock_scores(dataset)
    payload = _coverage_payload(scores)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"coverage_path={output_path}")
    print(f"row_count={payload['row_count']}")
    return 0


def _coverage_payload(scores: dict[tuple[object, str], StockScore]) -> dict[str, object]:
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
            name: _component_summary(name, score_values)
            for name in component_names
        },
        "missing_field_counts": dict(sorted(missing_counts.items())),
        "missing_field_rates": {
            field: round(count / row_count, 4) if row_count else 0.0
            for field, count in sorted(missing_counts.items())
        },
    }


def _component_summary(name: str, scores: list[StockScore]) -> dict[str, object]:
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


def _distribution(values: list[float]) -> dict[str, float]:
    if not values:
        return {"average": 0.0, "min": 0.0, "max": 0.0}
    return {
        "average": _average(values),
        "min": min(values),
        "max": max(values),
    }


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _optional_path(value: str | None) -> Path | None:
    return Path(value) if value else None


if __name__ == "__main__":
    raise SystemExit(main())
