from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from fintech_quant.features import StockScore, factor_pipeline_name


def build_factor_analysis_report(scores: Mapping[tuple[object, str], StockScore]) -> dict[str, object]:
    rows = [
        _score_row(trade_date, symbol, score)
        for (trade_date, symbol), score in sorted(scores.items(), key=lambda item: (item[0][0], item[0][1]))
    ]
    return {
        "pipeline": factor_pipeline_name(),
        "row_count": len(rows),
        "records": rows,
    }


def write_factor_analysis_report(path: Path, report: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _score_row(trade_date: object, symbol: str, score: StockScore) -> dict[str, object]:
    return {
        "trade_date": trade_date.isoformat() if hasattr(trade_date, "isoformat") else str(trade_date),
        "symbol": score.symbol or symbol,
        "total_score": score.total,
        "confidence": score.confidence,
        "missing_fields": list(score.missing_fields),
        "component_scores": {
            name: {
                "score": component.score,
                "max_score": component.max_score,
                "weight": round(component.max_score / 100.0, 4),
                "reasons": list(component.reasons),
            }
            for name, component in sorted(score.components.items())
        },
    }
