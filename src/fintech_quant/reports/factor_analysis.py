from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from fintech_quant.features import ScoreInput, StockScore, factor_pipeline_name


def build_factor_analysis_report(
    scores: Mapping[tuple[object, str], StockScore],
    score_inputs: Mapping[tuple[object, str], ScoreInput] | None = None,
) -> dict[str, object]:
    rows = [
        _score_row(trade_date, symbol, score, score_inputs.get((trade_date, symbol)) if score_inputs else None)
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


def _score_row(
    trade_date: object,
    symbol: str,
    score: StockScore,
    score_input: ScoreInput | None,
) -> dict[str, object]:
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
                "input_values": _component_inputs(name, score_input),
                "reasons": list(component.reasons),
            }
            for name, component in sorted(score.components.items())
        },
    }


def _component_inputs(name: str, score_input: ScoreInput | None) -> dict[str, object]:
    if score_input is None:
        return {}
    if name == "fundamental":
        return {
            "pe": score_input.pe,
            "pb": score_input.pb,
            "roe": score_input.roe,
            "growth": score_input.growth,
        }
    if name == "technical":
        return {
            "close_above_ma20": score_input.close_above_ma20,
            "close_above_ma60": score_input.close_above_ma60,
            "relative_strength": score_input.relative_strength,
            "rsi": score_input.rsi,
            "macd_positive": score_input.macd_positive,
            "volume_confirmed": score_input.volume_confirmed,
        }
    if name == "capital_flow":
        return {
            "main_net_inflow": score_input.main_net_inflow,
            "main_outflow_days": score_input.main_outflow_days,
            "margin_financing_positive": score_input.margin_financing_positive,
        }
    if name == "sentiment":
        return {
            "limit_up_streak": score_input.limit_up_streak,
            "dragon_tiger_positive": score_input.dragon_tiger_positive,
            "negative_event_count": score_input.negative_event_count,
        }
    return {}
