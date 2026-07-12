from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the post-close paper-trading and monitoring cycle."
    )
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--research-report", required=True)
    parser.add_argument("--features", required=True)
    parser.add_argument("--comparison", required=True)
    parser.add_argument("--dqn-report", default=None)
    parser.add_argument("--corporate-actions", default=None)
    parser.add_argument("--walk-forward", default=None)
    parser.add_argument("--data-health", default=None)
    parser.add_argument("--information-health", default=None)
    parser.add_argument("--account", default="data/paper/account.json")
    parser.add_argument("--targets-output", default=None)
    parser.add_argument("--paper-report", default=None)
    parser.add_argument("--dashboard-output", default="outputs/research_dashboard.html")
    parser.add_argument("--buy-threshold", type=float, default=70.0)
    parser.add_argument("--min-score-confidence", type=float, default=0.8)
    parser.add_argument("--max-position-weight", type=float, default=0.08)
    parser.add_argument("--max-targets", type=int, default=None)
    parser.add_argument("--dqn-default-action", choices=("buy", "hold", "sell"), default="hold")
    parser.add_argument("--dqn-flat-action", choices=("buy", "hold", "sell"), default="hold")
    parser.add_argument("--initial-cash", type=float, default=100000.0)
    parser.add_argument("--commission-rate", type=float, default=0.0003)
    parser.add_argument("--minimum-commission", type=float, default=5.0)
    parser.add_argument("--slippage-rate", type=float, default=0.0)
    args = parser.parse_args()

    paper_report = args.paper_report or f"outputs/paper_trading/report_{args.as_of}.json"
    targets_output = args.targets_output or f"outputs/paper_trading/targets_{args.as_of}.csv"

    paper_command = [
        "scripts/run_daily_paper_trading.py",
        "--research-report",
        args.research_report,
        "--features",
        args.features,
        "--as-of",
        args.as_of,
        "--account",
        args.account,
        "--targets-output",
        targets_output,
        "--paper-report",
        paper_report,
        "--buy-threshold",
        str(args.buy_threshold),
        "--min-score-confidence",
        str(args.min_score_confidence),
        "--max-position-weight",
        str(args.max_position_weight),
        "--initial-cash",
        str(args.initial_cash),
        "--commission-rate",
        str(args.commission_rate),
        "--minimum-commission",
        str(args.minimum_commission),
        "--slippage-rate",
        str(args.slippage_rate),
    ]
    if args.max_targets is not None:
        paper_command.extend(["--max-targets", str(args.max_targets)])
    if args.corporate_actions:
        paper_command.extend(["--corporate-actions", args.corporate_actions])
    if args.dqn_report:
        paper_command.extend(
            [
                "--dqn-report",
                args.dqn_report,
                "--dqn-default-action",
                args.dqn_default_action,
                "--dqn-flat-action",
                args.dqn_flat_action,
            ]
        )
    _run(paper_command)

    dashboard_command = [
        "scripts/build_research_dashboard.py",
        "--comparison",
        args.comparison,
        "--paper-report",
        paper_report,
        "--run-report",
        args.research_report,
        "--output",
        args.dashboard_output,
    ]
    if args.walk_forward:
        dashboard_command.extend(["--walk-forward", args.walk_forward])
    if args.data_health:
        dashboard_command.extend(["--data-health", args.data_health])
    if args.information_health:
        dashboard_command.extend(["--information-health", args.information_health])
    _run(dashboard_command)

    print(f"targets_path={targets_output}")
    print(f"paper_report_path={paper_report}")
    print(f"dashboard_path={args.dashboard_output}")
    return 0


def _run(command: list[str]) -> None:
    subprocess.run([sys.executable, *command], cwd=ROOT, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
