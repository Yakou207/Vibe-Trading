from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fintech_quant.execution.paper_account import (  # noqa: E402
    load_paper_account,
    run_paper_trading_day,
    write_paper_account,
    write_paper_report,
)
from scripts.generate_strategy_targets import (  # noqa: E402
    generate_targets,
    load_rl_signals,
    write_targets,
)
from scripts.export_dqn_signals import export_signals  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the daily post-close paper-trading loop from research output."
    )
    parser.add_argument("--research-report", required=True, help="Research run_report.json with scores and risk warnings.")
    parser.add_argument("--features", required=True, help="Feature CSV with symbol,trade_date,close and optional A-share flags.")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--account", default="data/paper/account.json")
    parser.add_argument("--targets-output", default=None)
    parser.add_argument("--paper-report", default=None)
    parser.add_argument("--buy-threshold", type=float, default=70.0)
    parser.add_argument("--min-score-confidence", type=float, default=0.8)
    parser.add_argument("--max-position-weight", type=float, default=0.08)
    parser.add_argument("--max-targets", type=int, default=None)
    parser.add_argument("--rl-signals", default=None, help="Optional CSV with symbol,trade_date,rl_action.")
    parser.add_argument("--dqn-report", default=None, help="Optional DQN run_report.json used as RL overlay signals.")
    parser.add_argument("--dqn-default-action", choices=("buy", "hold", "sell"), default="hold")
    parser.add_argument("--dqn-flat-action", choices=("buy", "hold", "sell"), default="hold")
    parser.add_argument("--initial-cash", type=float, default=100000.0)
    parser.add_argument("--commission-rate", type=float, default=0.0003)
    parser.add_argument("--slippage-rate", type=float, default=0.0)
    args = parser.parse_args()
    if args.rl_signals and args.dqn_report:
        raise SystemExit("--rl-signals and --dqn-report cannot be used together")

    as_of = date.fromisoformat(args.as_of)
    targets_path = Path(args.targets_output or f"outputs/paper_trading/targets_{args.as_of}.csv")
    paper_report_path = Path(args.paper_report or f"outputs/paper_trading/report_{args.as_of}.json")

    research_report = _load_json(Path(args.research_report))
    targets = generate_targets(
        research_report,
        as_of=args.as_of,
        buy_threshold=args.buy_threshold,
        min_score_confidence=args.min_score_confidence,
        max_position_weight=args.max_position_weight,
        max_targets=args.max_targets,
        rl_signals=_load_overlay_signals(args),
    )
    write_targets(targets_path, targets)

    account_path = Path(args.account)
    account = load_paper_account(account_path, initial_cash=args.initial_cash)
    result = run_paper_trading_day(
        account,
        targets={str(row["symbol"]): float(row["target_weight"]) for row in targets},
        bars=_load_feature_bars(Path(args.features), as_of),
        as_of=as_of,
        commission_rate=args.commission_rate,
        slippage_rate=args.slippage_rate,
    )
    write_paper_account(account_path, result.account)
    write_paper_report(paper_report_path, result)

    print(f"account_path={account_path}")
    print(f"targets_path={targets_path}")
    print(f"paper_report_path={paper_report_path}")
    print(f"target_count={len(targets)}")
    print(f"trade_count={len(result.trades)}")
    print(f"blocked_order_count={len(result.blocked_orders)}")
    print(f"ending_equity={result.nav['equity']}")
    return 0


def _load_feature_bars(path: Path, as_of: date) -> dict[str, dict[str, object]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return {
            str(row["symbol"]): dict(row)
            for row in reader
            if date.fromisoformat(str(row["trade_date"])) == as_of
        }


def _load_overlay_signals(args: argparse.Namespace) -> dict[str, str]:
    if args.rl_signals:
        return load_rl_signals(Path(args.rl_signals), args.as_of)
    if args.dqn_report:
        report = _load_json(Path(args.dqn_report))
        return {
            str(row["symbol"]): str(row["rl_action"])
            for row in export_signals(
                report,
                as_of=args.as_of,
                default_action=args.dqn_default_action,
                flat_action=args.dqn_flat_action,
            )
        }
    return {}


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
