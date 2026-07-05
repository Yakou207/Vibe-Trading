from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.data import normalize_a_share_symbol  # noqa: E402
from fintech_quant.research.dataset import FeatureRow, ResearchDataset, SupplementalRow, load_research_dataset  # noqa: E402
from fintech_quant.research.scoring import build_score_input  # noqa: E402
from fintech_quant.features import ScoreInput, StockScore, score_stock  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Explain one stock's multi-factor A-share analysis.")
    parser.add_argument("--features", required=True)
    parser.add_argument("--universe", required=True)
    parser.add_argument("--information", default=None)
    parser.add_argument("--fundamentals", default=None)
    parser.add_argument("--capital-flow", default=None)
    parser.add_argument("--market-state", default=None)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--output", default="outputs/stock_analysis_explanation.json")
    args = parser.parse_args()

    dataset = load_research_dataset(
        Path(args.features),
        Path(args.universe),
        fundamentals_path=_optional_path(args.fundamentals),
        capital_flow_path=_optional_path(args.capital_flow),
        market_state_path=_optional_path(args.market_state),
        information_path=_optional_path(args.information),
    )
    symbol = normalize_a_share_symbol(args.symbol)
    trade_date = date.fromisoformat(args.trade_date)
    feature_row = _find_feature_row(dataset, symbol, trade_date)
    score_input = build_score_input(
        feature_row,
        _supplement_for(dataset.fundamentals, symbol, trade_date),
        _supplement_for(dataset.capital_flow, symbol, trade_date),
        dataset.information_records,
    )
    score = score_stock(score_input)
    payload = _explanation_payload(feature_row, score_input, score)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"analysis_path={output_path}")
    print(f"symbol={payload['symbol']}")
    print(f"trade_date={payload['trade_date']}")
    print(f"total_score={payload['total_score']}")
    return 0


def _find_feature_row(dataset: ResearchDataset, symbol: str, trade_date: date) -> FeatureRow:
    for row in dataset.features:
        if row.symbol == symbol and row.trade_date == trade_date:
            return row
    raise SystemExit(f"No feature row found for {symbol} on {trade_date.isoformat()}")


def _supplement_for(
    rows: dict[tuple[str, date | None], SupplementalRow],
    symbol: str,
    trade_date: date,
) -> SupplementalRow | None:
    return rows.get((symbol, trade_date)) or rows.get((symbol, None))


def _explanation_payload(
    feature_row: FeatureRow,
    score_input: ScoreInput,
    score: StockScore,
) -> dict[str, object]:
    return {
        "symbol": score.symbol,
        "trade_date": feature_row.trade_date.isoformat(),
        "pipeline": "a_share_daily_factor_pipeline_v0",
        "total_score": score.total,
        "confidence": score.confidence,
        "missing_fields": list(score.missing_fields),
        "components": {
            name: {
                "score": component.score,
                "max_score": component.max_score,
                "weight_pct": component.max_score,
                "reasons": list(component.reasons),
            }
            for name, component in sorted(score.components.items())
        },
        "inputs": {
            "fundamental": {
                "pe": score_input.pe,
                "pb": score_input.pb,
                "roe": score_input.roe,
                "growth": score_input.growth,
            },
            "technical": {
                "close_above_ma20": score_input.close_above_ma20,
                "close_above_ma60": score_input.close_above_ma60,
                "relative_strength": score_input.relative_strength,
                "rsi": score_input.rsi,
                "macd_positive": score_input.macd_positive,
                "volume_confirmed": score_input.volume_confirmed,
            },
            "capital_flow": {
                "main_net_inflow": score_input.main_net_inflow,
                "main_outflow_days": score_input.main_outflow_days,
                "margin_financing_positive": score_input.margin_financing_positive,
            },
            "sentiment": {
                "limit_up_streak": score_input.limit_up_streak,
                "dragon_tiger_positive": score_input.dragon_tiger_positive,
                "negative_event_count": score_input.negative_event_count,
            },
        },
    }


def _optional_path(value: str | None) -> Path | None:
    return Path(value) if value else None


if __name__ == "__main__":
    raise SystemExit(main())
