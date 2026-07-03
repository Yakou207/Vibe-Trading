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

from fintech_quant.risk import RiskInput, RiskLimits, evaluate_risk  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate risk warnings from realtime A-share quotes.")
    parser.add_argument("--quotes", required=True, help="CSV produced by scripts/fetch_realtime_quotes.py.")
    parser.add_argument("--output", default="outputs/realtime_risk.json")
    parser.add_argument("--drop-threshold", type=float, default=-0.03)
    parser.add_argument("--broad-market-drop-threshold", type=int, default=15)
    args = parser.parse_args()

    quote_stats = _broad_market_drop_stats(Path(args.quotes), args.drop_threshold)
    drop_count = quote_stats["drop_count"]
    risk_input = RiskInput(broad_market_drop_gt_3pct_count=drop_count)
    evaluation = evaluate_risk(
        risk_input,
        RiskLimits(broad_market_drop_threshold=args.broad_market_drop_threshold),
    )
    payload = {
        "risk_input": {"broad_market_drop_gt_3pct_count": drop_count},
        "limits": {"broad_market_drop_threshold": args.broad_market_drop_threshold},
        "valid_quote_rows": quote_stats["valid_rows"],
        "skipped_quote_rows": quote_stats["skipped_rows"],
        "action": evaluation.action.value,
        "warnings": [
            {
                "layer": warning.layer,
                "rule": warning.rule,
                "action": warning.action.value,
                "message": warning.message,
            }
            for warning in evaluation.warnings
        ],
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"risk_action={evaluation.action.value}")
    print(f"broad_market_drop_gt_3pct_count={drop_count}")
    print(f"valid_quote_rows={quote_stats['valid_rows']}")
    print(f"skipped_quote_rows={quote_stats['skipped_rows']}")
    print(f"output={args.output}")
    return 0


def _broad_market_drop_stats(path: Path, drop_threshold: float) -> dict[str, int]:
    drop_count = 0
    valid_rows = 0
    skipped_rows = 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if "change_pct" not in (reader.fieldnames or ()):
            raise ValueError("Realtime quote CSV must contain change_pct")
        for row in reader:
            try:
                change_pct = _float(row["change_pct"])
            except (TypeError, ValueError):
                skipped_rows += 1
                continue
            valid_rows += 1
            if change_pct < drop_threshold:
                drop_count += 1
    return {"drop_count": drop_count, "valid_rows": valid_rows, "skipped_rows": skipped_rows}


def _float(value: object) -> float:
    return float(str(value).replace(",", "").strip())


if __name__ == "__main__":
    raise SystemExit(main())
