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
from fintech_quant.research.preflight import require_passing_data_health  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a reproducible A-share research baseline report.")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--features", required=True)
    parser.add_argument("--execution-prices", default=None)
    parser.add_argument("--corporate-actions", default=None)
    parser.add_argument("--universe", required=True)
    parser.add_argument("--information", default=None)
    parser.add_argument("--fundamentals", default=None)
    parser.add_argument("--capital-flow", default=None)
    parser.add_argument("--market-state", default=None)
    parser.add_argument("--membership", default=None)
    parser.add_argument("--data-health", default=None)
    parser.add_argument("--require-point-in-time", action="store_true")
    parser.add_argument("--output-root", default="outputs/research_runs")
    parser.add_argument("--initial-cash", type=float, default=100000.0)
    parser.add_argument("--max-position-weight", type=float, default=0.08)
    parser.add_argument("--commission-rate", type=float, default=0.0003)
    parser.add_argument("--minimum-commission", type=float, default=5.0)
    parser.add_argument("--no-stamp-duty", action="store_true")
    parser.add_argument("--slippage-rate", type=float, default=0.0005)
    parser.add_argument("--execution-delay-sessions", type=int, default=1)
    parser.add_argument("--buy-threshold", type=float, default=70.0)
    parser.add_argument("--min-score-confidence", type=float, default=0.8)
    parser.add_argument("--max-portfolio-drawdown", type=float, default=0.15)
    parser.add_argument("--enable-drawdown-control", action="store_true")
    parser.add_argument("--reduce-portfolio-drawdown", type=float, default=0.08)
    parser.add_argument("--recover-reduced-drawdown", type=float, default=0.08)
    parser.add_argument("--recover-normal-drawdown", type=float, default=0.06)
    parser.add_argument("--max-single-position-drawdown", type=float, default=0.08)
    parser.add_argument("--max-goodwill-ratio", type=float, default=0.30)
    parser.add_argument("--max-pledge-ratio", type=float, default=0.50)
    parser.add_argument("--max-main-outflow-days", type=int, default=3)
    parser.add_argument("--broad-market-drop-threshold", type=int, default=15)
    args = parser.parse_args()

    run_id = args.run_id or f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-baseline"
    try:
        if args.require_point_in_time:
            require_passing_data_health(_optional_path(args.data_health), _research_inputs(args))
        config = ResearchRunConfig(
            run_id=run_id,
            features_path=Path(args.features),
            execution_prices_path=_optional_path(args.execution_prices),
            corporate_actions_path=_optional_path(args.corporate_actions),
            universe_path=Path(args.universe),
            information_path=_optional_path(args.information),
            fundamentals_path=_optional_path(args.fundamentals),
            capital_flow_path=_optional_path(args.capital_flow),
            market_state_path=_optional_path(args.market_state),
            membership_path=_optional_path(args.membership),
            require_point_in_time=args.require_point_in_time,
            initial_cash=args.initial_cash,
            max_position_weight=args.max_position_weight,
            commission_rate=args.commission_rate,
            minimum_commission=args.minimum_commission,
            include_stamp_duty=not args.no_stamp_duty,
            slippage_rate=args.slippage_rate,
            execution_delay_sessions=args.execution_delay_sessions,
            buy_threshold=args.buy_threshold,
            min_score_confidence=args.min_score_confidence,
            max_portfolio_drawdown=args.max_portfolio_drawdown,
            enable_drawdown_control=args.enable_drawdown_control,
            reduce_portfolio_drawdown=args.reduce_portfolio_drawdown,
            recover_reduced_drawdown=args.recover_reduced_drawdown,
            recover_normal_drawdown=args.recover_normal_drawdown,
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


def _research_inputs(args: argparse.Namespace) -> dict[str, Path | None]:
    return {
        "features": Path(args.features),
        "execution_prices": _optional_path(args.execution_prices),
        "corporate_actions": _optional_path(args.corporate_actions),
        "universe": Path(args.universe),
        "membership": _optional_path(args.membership),
        "fundamentals": _optional_path(args.fundamentals),
        "capital_flow": _optional_path(args.capital_flow),
        "information": _optional_path(args.information),
        "market_state": _optional_path(args.market_state),
    }


if __name__ == "__main__":
    raise SystemExit(main())
