from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.reports.premarket_brief import (  # noqa: E402
    build_brief,
    dumps,
    ensure_outside,
    evaluate_auction,
    latest_complete_cycle,
    render_brief_html,
    write_once,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a read-only pre-market brief from the latest complete CSI 300 post-close "
            "cycle. A human places every order; nothing here touches paper evidence."
        )
    )
    parser.add_argument("--cycle-root", default="outputs/paper_trading/csi300_baseline/cycles")
    parser.add_argument("--cycle-dir", default=None, help="Explicit cycle; default is the latest.")
    parser.add_argument("--capital", type=float, default=100_000.0)
    parser.add_argument("--near-miss-floor", type=float, default=65.0)
    parser.add_argument("--output-root", default="outputs/premarket")
    parser.add_argument(
        "--protect",
        action="append",
        default=None,
        help="Evidence path that must never be written (repeatable; default data/paper).",
    )
    parser.add_argument(
        "--auction",
        action="store_true",
        help="After 09:25, check auction quotes against the existing brief.",
    )
    parser.add_argument("--quotes", default=None, help="CSV from scripts/fetch_realtime_quotes.py.")
    parser.add_argument("--near-limit-pct", type=float, default=0.01)
    parser.add_argument("--large-gap-pct", type=float, default=0.05)
    args = parser.parse_args()

    cycle_root = Path(args.cycle_root)
    cycle_dir = Path(args.cycle_dir) if args.cycle_dir else latest_complete_cycle(cycle_root)
    signal_date = json.loads((cycle_dir / "cycle_manifest.json").read_text(encoding="utf-8"))[
        "as_of"
    ]
    output_dir = Path(args.output_root) / signal_date
    protected = [cycle_root, cycle_dir, *(Path(p) for p in (args.protect or ["data/paper"]))]
    ensure_outside(output_dir, protected)

    if not args.auction:
        brief = build_brief(cycle_dir, args.capital, args.near_miss_floor)
        write_once(output_dir / "brief.json", dumps(brief))
        write_once(output_dir / "brief.html", render_brief_html(brief))
        print(f"signal_date={signal_date}")
        print(f"targets={len(brief['targets'])} near_miss={len(brief['near_miss'])}")
        watch = [item["symbol"] for item in (*brief["targets"], *brief["near_miss"])]
        print(f"quote_symbols={','.join(watch)}")
        print(f"output={output_dir / 'brief.html'}")
        return 0

    if not args.quotes:
        raise SystemExit("--quotes is required with --auction")
    brief_path = output_dir / "brief.json"
    if not brief_path.exists():
        raise SystemExit(f"{brief_path} not found; build the brief before the auction check")
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    with Path(args.quotes).open("r", encoding="utf-8", newline="") as handle:
        quotes = list(csv.DictReader(handle))
    auction = evaluate_auction(brief, quotes, args.near_limit_pct, args.large_gap_pct)
    write_once(output_dir / "auction.json", dumps(auction))
    write_once(output_dir / "brief_auction.html", render_brief_html(brief, auction))
    for check in auction["checks"]:
        if check["flags"]:
            print(f"{check['symbol']} {' '.join(check['flags'])}")
    print(f"output={output_dir / 'brief_auction.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
