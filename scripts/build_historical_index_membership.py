from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.data.historical_universe import (  # noqa: E402
    active_symbols,
    build_membership_intervals,
    load_membership_adjustments,
    load_membership_anchor,
    write_membership_csv,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build point-in-time index membership intervals from an official anchor and adjustments."
    )
    parser.add_argument("--anchor", required=True)
    parser.add_argument("--adjustments", required=True)
    parser.add_argument("--index-code", default="000300")
    parser.add_argument("--start", required=True)
    parser.add_argument("--expected-members", type=int, default=300)
    parser.add_argument("--source-fetched-at", default=None)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source_fetched_at = args.source_fetched_at or datetime.now(timezone.utc).isoformat()
    try:
        anchor = load_membership_anchor(
            Path(args.anchor),
            index_code=args.index_code,
            source_fetched_at=source_fetched_at,
        )
        adjustments = load_membership_adjustments(Path(args.adjustments))
        intervals = build_membership_intervals(
            anchor,
            adjustments,
            start=date.fromisoformat(args.start),
            expected_members=args.expected_members,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    write_membership_csv(Path(args.output), intervals)
    print(f"index_code={args.index_code}")
    print(f"interval_count={len(intervals)}")
    print(f"active_members={len(active_symbols(intervals, anchor.as_of))}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
