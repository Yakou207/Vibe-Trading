from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.research import ResearchRunConfig, run_research_baseline, write_run_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a reproducible A-share research baseline report.")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--features", required=True)
    parser.add_argument("--universe", required=True)
    parser.add_argument("--information", default=None)
    parser.add_argument("--fundamentals", default=None)
    parser.add_argument("--capital-flow", default=None)
    parser.add_argument("--market-state", default=None)
    parser.add_argument("--output-root", default="outputs/research_runs")
    parser.add_argument("--initial-cash", type=float, default=100000.0)
    parser.add_argument("--max-position-weight", type=float, default=0.08)
    parser.add_argument("--commission-rate", type=float, default=0.0003)
    parser.add_argument("--slippage-rate", type=float, default=0.0005)
    parser.add_argument("--buy-threshold", type=float, default=70.0)
    parser.add_argument("--min-score-confidence", type=float, default=0.8)
    parser.add_argument("--max-portfolio-drawdown", type=float, default=0.15)
    parser.add_argument("--max-single-position-drawdown", type=float, default=0.08)
    parser.add_argument("--max-goodwill-ratio", type=float, default=0.30)
    parser.add_argument("--max-pledge-ratio", type=float, default=0.50)
    parser.add_argument("--max-main-outflow-days", type=int, default=3)
    parser.add_argument("--broad-market-drop-threshold", type=int, default=15)
    args = parser.parse_args()

    run_id = args.run_id or f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-baseline"
    try:
        config = ResearchRunConfig(
            run_id=run_id,
            features_path=Path(args.features),
            universe_path=Path(args.universe),
            information_path=_optional_path(args.information),
            fundamentals_path=_optional_path(args.fundamentals),
            capital_flow_path=_optional_path(args.capital_flow),
            market_state_path=_optional_path(args.market_state),
            initial_cash=args.initial_cash,
            max_position_weight=args.max_position_weight,
            commission_rate=args.commission_rate,
            slippage_rate=args.slippage_rate,
            buy_threshold=args.buy_threshold,
            min_score_confidence=args.min_score_confidence,
            max_portfolio_drawdown=args.max_portfolio_drawdown,
            max_single_position_drawdown=args.max_single_position_drawdown,
            max_goodwill_ratio=args.max_goodwill_ratio,
            max_pledge_ratio=args.max_pledge_ratio,
            max_main_outflow_days=args.max_main_outflow_days,
            broad_market_drop_threshold=args.broad_market_drop_threshold,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    report = run_research_baseline(config)
    report_path = write_run_report(report, Path(args.output_root))
    print(f"report_path={report_path}")
    print(f"ending_equity={report.summary['ending_equity']}")
    print(f"total_return={report.summary['total_return']}")
    print(f"max_drawdown={report.summary['max_drawdown']}")
    return 0


def _optional_path(value: str | None) -> Path | None:
    return Path(value) if value else None


if __name__ == "__main__":
    raise SystemExit(main())
