from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.execution.paper_account import (  # noqa: E402
    load_paper_account,
    run_paper_trading_day,
    write_paper_account,
    write_paper_report,
)
from fintech_quant.backtesting import (  # noqa: E402
    AShareCostModel,
    CorporateAction,
    IndividualAShareDividendTaxPolicy,
    load_corporate_actions_csv,
    standard_drawdown_control_policy,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one post-close paper-trading rebalance.")
    parser.add_argument("--account", default="data/paper/account.json")
    parser.add_argument("--targets", required=True, help="CSV with symbol,target_weight.")
    parser.add_argument(
        "--prices",
        required=True,
        help="CSV with symbol,trade_date,close and optional A-share flags.",
    )
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--report", default="outputs/paper_trading/daily_report.json")
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

    as_of = date.fromisoformat(args.as_of)
    account_path = Path(args.account)
    account = load_paper_account(account_path, initial_cash=args.initial_cash)
    result = run_paper_trading_day(
        account,
        targets=_load_targets(Path(args.targets)),
        bars=_load_prices(Path(args.prices), as_of),
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
    write_paper_account(account_path, result.account)
    write_paper_report(Path(args.report), result)
    print(f"account_path={account_path}")
    print(f"report_path={args.report}")
    print(f"trade_count={len(result.trades)}")
    print(f"blocked_order_count={len(result.blocked_orders)}")
    print(f"ending_equity={result.nav['equity']}")
    return 0


def _load_targets(path: Path) -> dict[str, float]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return {
            str(row["symbol"]): float(row.get("raw_target_weight") or row["target_weight"])
            for row in reader
        }


def _load_prices(path: Path, as_of: date) -> dict[str, dict[str, object]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return {
            str(row["symbol"]): dict(row)
            for row in reader
            if date.fromisoformat(str(row["trade_date"])) == as_of
        }


def _load_corporate_actions(
    value: str | None,
    as_of: date,
) -> tuple[CorporateAction, ...]:
    if value is None:
        return ()
    return tuple(
        action for action in load_corporate_actions_csv(Path(value)) if action.ex_date == as_of
    )


if __name__ == "__main__":
    raise SystemExit(main())
