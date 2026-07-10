from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.research.data_health import (  # noqa: E402
    DataHealthThresholds,
    validate_research_data,
)
from fintech_quant.research.dataset import load_research_dataset  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate point-in-time research data before strategy execution.")
    parser.add_argument("--features", required=True)
    parser.add_argument("--universe", required=True)
    parser.add_argument("--membership", required=True)
    parser.add_argument("--fundamentals", required=True)
    parser.add_argument("--capital-flow", required=True)
    parser.add_argument("--information", default=None)
    parser.add_argument("--market-state", default=None)
    parser.add_argument("--expected-members", type=int, default=300)
    parser.add_argument("--minimum-price-coverage", type=float, default=0.95)
    parser.add_argument("--minimum-fundamental-coverage", type=float, default=0.80)
    parser.add_argument("--minimum-capital-flow-coverage", type=float, default=0.95)
    parser.add_argument("--fundamental-warmup-days", type=int, default=180)
    parser.add_argument("--maximum-fundamental-age-days", type=int, default=180)
    parser.add_argument("--maximum-capital-flow-age-sessions", type=int, default=3)
    parser.add_argument("--output", default="outputs/data_health.json")
    args = parser.parse_args()

    dataset = load_research_dataset(
        Path(args.features),
        Path(args.universe),
        fundamentals_path=Path(args.fundamentals),
        capital_flow_path=Path(args.capital_flow),
        market_state_path=Path(args.market_state) if args.market_state else None,
        information_path=Path(args.information) if args.information else None,
        membership_path=Path(args.membership),
        require_point_in_time=True,
    )
    report = validate_research_data(
        dataset,
        thresholds=DataHealthThresholds(
            expected_members=args.expected_members,
            minimum_price_coverage=args.minimum_price_coverage,
            minimum_fundamental_coverage=args.minimum_fundamental_coverage,
            minimum_capital_flow_coverage=args.minimum_capital_flow_coverage,
            fundamental_warmup_days=args.fundamental_warmup_days,
            maximum_fundamental_age_days=args.maximum_fundamental_age_days,
            maximum_capital_flow_age_sessions=args.maximum_capital_flow_age_sessions,
        ),
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.to_json(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"data_health={output_path}")
    print(f"passed={str(report.passed).lower()}")
    print(f"issue_count={len(report.issues)}")
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
