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
    PaperAccount,
    load_paper_account,
    run_paper_trading_day,
    write_paper_account,
    write_paper_report,
)
from fintech_quant.backtesting import (  # noqa: E402
    AShareCostModel,
    CorporateAction,
    IndividualAShareDividendTaxPolicy,
    drawdown_exposure_multiplier,
    load_corporate_actions_csv,
    standard_drawdown_control_policy,
)
from fintech_quant.risk import RiskInput, RiskLimits, evaluate_risk  # noqa: E402
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
    parser.add_argument(
        "--research-report",
        required=True,
        help="Research run_report.json with scores and risk warnings.",
    )
    parser.add_argument(
        "--features",
        required=True,
        help="Feature CSV with symbol,trade_date,close and optional A-share flags.",
    )
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--account", default="data/paper/account.json")
    parser.add_argument("--targets-output", default=None)
    parser.add_argument("--paper-report", default=None)
    parser.add_argument("--buy-threshold", type=float, default=70.0)
    parser.add_argument("--min-score-confidence", type=float, default=0.8)
    parser.add_argument("--max-position-weight", type=float, default=0.08)
    parser.add_argument("--max-targets", type=int, default=None)
    parser.add_argument(
        "--rl-signals", default=None, help="Optional CSV with symbol,trade_date,rl_action."
    )
    parser.add_argument(
        "--dqn-report",
        default=None,
        help="Optional DQN run_report.json used as RL overlay signals.",
    )
    parser.add_argument("--dqn-default-action", choices=("buy", "hold", "sell"), default="hold")
    parser.add_argument("--dqn-flat-action", choices=("buy", "hold", "sell"), default="hold")
    parser.add_argument("--initial-cash", type=float, default=100000.0)
    parser.add_argument("--commission-rate", type=float, default=0.0003)
    parser.add_argument("--minimum-commission", type=float, default=None)
    parser.add_argument("--slippage-rate", type=float, default=0.0)
    parser.add_argument("--no-stamp-duty", action="store_true")
    parser.add_argument("--no-drawdown-control", action="store_true")
    parser.add_argument("--corporate-actions", default=None)
    parser.add_argument("--no-dividend-tax", action="store_true")
    parser.add_argument(
        "--rights-issue-policy",
        choices=("fail_closed", "do_not_subscribe"),
        default="do_not_subscribe",
    )
    args = parser.parse_args()
    if args.rl_signals and args.dqn_report:
        raise SystemExit("--rl-signals and --dqn-report cannot be used together")

    as_of = date.fromisoformat(args.as_of)
    targets_path = Path(args.targets_output or f"outputs/paper_trading/targets_{args.as_of}.csv")
    paper_report_path = Path(args.paper_report or f"outputs/paper_trading/report_{args.as_of}.json")

    research_report = _load_json(Path(args.research_report))
    account_path = Path(args.account)
    account = load_paper_account(account_path, initial_cash=args.initial_cash)
    bars = _load_feature_bars(Path(args.features), as_of)

    result = run_paper_trading_day(
        account,
        targets=account.pending_targets,
        bars=bars,
        as_of=as_of,
        commission_rate=args.commission_rate,
        slippage_rate=args.slippage_rate,
        drawdown_policy=(None if args.no_drawdown_control else standard_drawdown_control_policy()),
        corporate_actions=_load_corporate_actions(args.corporate_actions, as_of),
        dividend_tax_policy=(None if args.no_dividend_tax else IndividualAShareDividendTaxPolicy()),
        cost_model=AShareCostModel(
            commission_rate=args.commission_rate,
            minimum_commission=(
                args.minimum_commission
                if args.minimum_commission is not None
                else (0.0 if args.commission_rate == 0 else 5.0)
            ),
            include_stamp_duty=not args.no_stamp_duty,
        ),
        rights_issue_policy=args.rights_issue_policy,
    )
    target_risk_warnings = _actual_position_risk_warnings(result.account, bars, as_of)
    target_report = {
        **research_report,
        "risk_warnings": [
            *list(research_report.get("risk_warnings", [])),
            *target_risk_warnings,
        ],
    }
    exposure_multiplier = (
        1.0
        if args.no_drawdown_control or result.account.drawdown_control_state is None
        else drawdown_exposure_multiplier(result.account.drawdown_control_state)
    )
    targets = generate_targets(
        target_report,
        as_of=args.as_of,
        buy_threshold=args.buy_threshold,
        min_score_confidence=args.min_score_confidence,
        max_position_weight=args.max_position_weight,
        max_targets=args.max_targets,
        rl_signals=_load_overlay_signals(args),
        portfolio_exposure_multiplier=exposure_multiplier,
    )
    write_targets(targets_path, targets)
    result.account.pending_targets = {
        str(row["symbol"]): float(row["raw_target_weight"]) for row in targets
    }
    result.account.pending_signal_date = as_of
    result.nav["executed_signal_date"] = (
        account.pending_signal_date.isoformat() if account.pending_signal_date else None
    )
    result.nav["queued_signal_date"] = as_of.isoformat()
    write_paper_account(account_path, result.account)
    write_paper_report(
        paper_report_path,
        result,
        target_risk_warnings=target_risk_warnings,
    )

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


def _actual_position_risk_warnings(
    account: PaperAccount,
    bars: dict[str, dict[str, object]],
    as_of: date,
) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    for symbol, position in sorted(account.positions.items()):
        bar = bars.get(symbol)
        if bar is None or float(position.cost_basis) <= 0:
            continue
        close = float(bar["close"])
        drawdown = round(
            max(0.0, (float(position.cost_basis) - close) / float(position.cost_basis)),
            6,
        )
        evaluation = evaluate_risk(RiskInput(single_position_drawdown=drawdown), RiskLimits())
        for warning in evaluation.warnings:
            warnings.append(
                {
                    "trade_date": as_of.isoformat(),
                    "symbol": symbol,
                    "rule": warning.rule,
                    "action": warning.action.value,
                    "observed_value": warning.observed_value,
                    "threshold_value": warning.threshold_value,
                }
            )
    return warnings


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


def _load_corporate_actions(
    value: str | None,
    as_of: date,
) -> tuple[CorporateAction, ...]:
    if value is None:
        return ()
    return tuple(
        action for action in load_corporate_actions_csv(Path(value)) if action.ex_date == as_of
    )


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
