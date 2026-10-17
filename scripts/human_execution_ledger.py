from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.execution.human_ledger import (  # noqa: E402
    LedgerError,
    append_entry,
    compare_to_paper,
    load_ledger,
)
from fintech_quant.reports.premarket_brief import dumps, ensure_outside  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Human execution ledger. Records what a person actually traded and compares it "
            "with the paper account. Never feeds the V2 paper evidence."
        )
    )
    parser.add_argument("--ledger", default="data/human_execution/ledger.csv")
    parser.add_argument("--brief-root", default="outputs/premarket")
    parser.add_argument("--cycle-root", default="outputs/paper_trading/csi300_baseline/cycles")
    parser.add_argument("--protect", action="append", default=None)
    commands = parser.add_subparsers(dest="command", required=True)

    add = commands.add_parser("add", help="Append one validated row.")
    add.add_argument("--trade-date", required=True)
    add.add_argument("--signal-date", required=True)
    add.add_argument("--symbol", required=True)
    add.add_argument("--action", required=True, choices=("buy", "sell", "skip"))
    add.add_argument("--shares", default="")
    add.add_argument("--fill-price", default="")
    add.add_argument("--fees", default="")
    add.add_argument("--skip-reason", default="")
    add.add_argument("--note", default="")

    report = commands.add_parser("report", help="Compare human fills with the paper account.")
    report.add_argument("--signal-date", required=True)
    report.add_argument("--output", default=None)
    args = parser.parse_args()

    cycle_root = Path(args.cycle_root)
    protected = [cycle_root, *(Path(p) for p in (args.protect or ["data/paper"]))]
    ledger = Path(args.ledger)
    ensure_outside(ledger, protected)

    try:
        if args.command == "add":
            brief = _load_brief(Path(args.brief_root), args.signal_date)
            row = append_entry(
                ledger,
                {
                    "trade_date": args.trade_date,
                    "signal_date": args.signal_date,
                    "symbol": args.symbol,
                    "action": args.action,
                    "shares": args.shares,
                    "fill_price": args.fill_price,
                    "fees": args.fees,
                    "skip_reason": args.skip_reason,
                    "note": args.note,
                },
                brief,
            )
            print(f"appended={json.dumps(row, ensure_ascii=False, sort_keys=True)}")
            if brief is None:
                print("warning=no brief found; limit-band check skipped")
            return 0

        brief = _load_brief(Path(args.brief_root), args.signal_date)
        if brief is None:
            raise SystemExit(f"no brief for signal date {args.signal_date}")
        output = Path(
            args.output
            or Path(args.brief_root) / args.signal_date / "human_execution_report.json"
        )
        ensure_outside(output, protected)
        paper_trades = _paper_trades(cycle_root, args.signal_date)
        result = compare_to_paper(load_ledger(ledger), brief, paper_trades)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(dumps(result), encoding="utf-8")
        print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True))
        print(f"output={output}")
        return 0
    except LedgerError as exc:
        print(f"ledger_error={exc}", file=sys.stderr)
        return 2


def _load_brief(brief_root: Path, signal_date: str) -> dict | None:
    path = brief_root / signal_date / "brief.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _paper_trades(cycle_root: Path, signal_date: str) -> list[dict] | None:
    """Trades of the cycle that executed ``signal_date`` targets, read-only and hash-checked."""
    for cycle in sorted(p for p in cycle_root.iterdir() if p.is_dir()):
        paper = cycle / "paper_report.json"
        manifest = cycle / "cycle_manifest.json"
        if not (paper.is_file() and manifest.is_file()):
            continue
        payload = json.loads(paper.read_text(encoding="utf-8"))
        if payload.get("nav", {}).get("executed_signal_date") != signal_date:
            continue
        expected = json.loads(manifest.read_text(encoding="utf-8"))["artifacts"]["paper_report"]
        if hashlib.sha256(paper.read_bytes()).hexdigest() != expected["sha256"]:
            raise SystemExit(f"{paper} does not match its cycle manifest hash")
        return list(payload.get("trades", []))
    return None


if __name__ == "__main__":
    raise SystemExit(main())
