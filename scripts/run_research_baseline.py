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
    args = parser.parse_args()

    run_id = args.run_id or f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-baseline"
    report = run_research_baseline(
        ResearchRunConfig(
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
        )
    )
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
