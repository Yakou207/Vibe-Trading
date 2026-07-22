from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.data import normalize_a_share_symbol  # noqa: E402
from fintech_quant.execution.broker import (  # noqa: E402
    SIMULATION_MODE,
    build_order_instructions,
    write_order_instructions,
)
from fintech_quant.execution.paper_account import load_paper_account  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build QMT bridge order instructions from the canonical account and queued targets."
    )
    parser.add_argument("--account", required=True)
    parser.add_argument("--targets", required=True, help="targets.csv from the post-close cycle.")
    parser.add_argument("--quotes", required=True, help="CSV with symbol and price columns.")
    parser.add_argument("--as-of", required=True, help="Execution session (YYYY-MM-DD, the T+1 day).")
    parser.add_argument("--output", default=None)
    parser.add_argument("--limit-offset", type=float, default=0.002)
    parser.add_argument("--initial-cash", type=float, default=100000.0)
    args = parser.parse_args()

    as_of = date.fromisoformat(args.as_of)
    account_path = Path(args.account)
    targets_path = Path(args.targets)
    quotes_path = Path(args.quotes)
    account = load_paper_account(account_path, initial_cash=args.initial_cash)
    if account.last_processed_date is not None and as_of <= account.last_processed_date:
        raise SystemExit(
            f"--as-of {as_of.isoformat()} must be after the account date "
            f"{account.last_processed_date.isoformat()}"
        )

    targets = _load_targets(targets_path)
    quotes = _load_quotes(quotes_path)
    orders, skipped = build_order_instructions(
        account,
        targets=targets,
        quotes=quotes,
        as_of=as_of,
        limit_offset=args.limit_offset,
    )
    output = Path(args.output or f"outputs/live_bridge/{as_of.isoformat()}/order_instructions.json")
    payload = write_order_instructions(
        output,
        orders=orders,
        skipped=skipped,
        as_of=as_of,
        mode=SIMULATION_MODE,
        source_paths={"account": account_path, "targets": targets_path, "quotes": quotes_path},
    )
    print(f"orders={len(orders)} skipped={len(skipped)}")
    print(f"output={output}")
    print(json.dumps(payload["skipped"], ensure_ascii=False))
    return 0


def _load_targets(path: Path) -> dict[str, float]:
    targets: dict[str, float] = {}
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            targets[normalize_a_share_symbol(row["symbol"])] = float(row["target_weight"])
    return targets


def _load_quotes(path: Path) -> dict[str, float]:
    quotes: dict[str, float] = {}
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            raw_price = (row.get("price") or "").strip()
            if not raw_price:
                continue
            quotes[normalize_a_share_symbol(row["symbol"])] = float(raw_price)
    return quotes


if __name__ == "__main__":
    raise SystemExit(main())
