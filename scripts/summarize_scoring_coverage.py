from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.reports import build_scoring_coverage_report  # noqa: E402
from fintech_quant.research.dataset import load_research_dataset  # noqa: E402
from fintech_quant.research.preflight import require_passing_data_health  # noqa: E402
from fintech_quant.research.scoring import build_stock_scores  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize multi-factor scoring coverage and missing inputs.")
    parser.add_argument("--features", required=True)
    parser.add_argument("--universe", required=True)
    parser.add_argument("--information", default=None)
    parser.add_argument("--fundamentals", default=None)
    parser.add_argument("--capital-flow", default=None)
    parser.add_argument("--market-state", default=None)
    parser.add_argument("--membership", default=None)
    parser.add_argument("--data-health", default=None)
    parser.add_argument("--require-point-in-time", action="store_true")
    parser.add_argument("--output", default="outputs/scoring_coverage.json")
    args = parser.parse_args()

    if args.require_point_in_time:
        require_passing_data_health(_optional_path(args.data_health), _research_inputs(args))
    dataset = load_research_dataset(
        Path(args.features),
        Path(args.universe),
        fundamentals_path=_optional_path(args.fundamentals),
        capital_flow_path=_optional_path(args.capital_flow),
        market_state_path=_optional_path(args.market_state),
        information_path=_optional_path(args.information),
        membership_path=_optional_path(args.membership),
        require_point_in_time=args.require_point_in_time,
    )
    scores = build_stock_scores(dataset)
    payload = build_scoring_coverage_report(scores)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"coverage_path={output_path}")
    print(f"row_count={payload['row_count']}")
    return 0


def _optional_path(value: str | None) -> Path | None:
    return Path(value) if value else None


def _research_inputs(args: argparse.Namespace) -> dict[str, Path | None]:
    return {
        "features": Path(args.features),
        "universe": Path(args.universe),
        "membership": _optional_path(args.membership),
        "fundamentals": _optional_path(args.fundamentals),
        "capital_flow": _optional_path(args.capital_flow),
        "information": _optional_path(args.information),
        "market_state": _optional_path(args.market_state),
    }


if __name__ == "__main__":
    raise SystemExit(main())
