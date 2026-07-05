from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.reports import build_factor_analysis_report, write_factor_analysis_report  # noqa: E402
from fintech_quant.research.dataset import load_research_dataset  # noqa: E402
from fintech_quant.research.scoring import build_stock_scores  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Export per-stock 35/25/25/15 multi-factor analysis.")
    parser.add_argument("--features", required=True)
    parser.add_argument("--universe", required=True)
    parser.add_argument("--information", default=None)
    parser.add_argument("--fundamentals", default=None)
    parser.add_argument("--capital-flow", default=None)
    parser.add_argument("--market-state", default=None)
    parser.add_argument("--output", default="outputs/stock_score_analysis.json")
    args = parser.parse_args()

    dataset = load_research_dataset(
        Path(args.features),
        Path(args.universe),
        information_path=_optional_path(args.information),
        fundamentals_path=_optional_path(args.fundamentals),
        capital_flow_path=_optional_path(args.capital_flow),
        market_state_path=_optional_path(args.market_state),
    )
    report = build_factor_analysis_report(build_stock_scores(dataset))
    output_path = Path(args.output)
    write_factor_analysis_report(output_path, report)
    print(f"analysis_path={output_path}")
    print(f"row_count={report['row_count']}")
    return 0


def _optional_path(value: str | None) -> Path | None:
    return Path(value) if value else None


if __name__ == "__main__":
    raise SystemExit(main())
