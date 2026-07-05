from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.risk import RiskInput, RiskLimits, evaluate_risk  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate risk warnings from realtime A-share quotes.")
    parser.add_argument("--quotes", required=True, help="CSV produced by scripts/fetch_realtime_quotes.py.")
    parser.add_argument("--risk-input", default=None, help="Optional JSON object with RiskInput fields.")
    parser.add_argument("--output", default="outputs/realtime_risk.json")
    parser.add_argument("--drop-threshold", type=float, default=-0.03)
    parser.add_argument("--max-position-weight", type=float, default=0.08)
    parser.add_argument("--max-portfolio-drawdown", type=float, default=0.15)
    parser.add_argument("--max-single-position-drawdown", type=float, default=0.08)
    parser.add_argument("--max-goodwill-ratio", type=float, default=0.30)
    parser.add_argument("--max-pledge-ratio", type=float, default=0.50)
    parser.add_argument("--max-main-outflow-days", type=int, default=3)
    parser.add_argument("--broad-market-drop-threshold", type=int, default=15)
    args = parser.parse_args()

    try:
        quote_stats = _broad_market_drop_stats(Path(args.quotes), args.drop_threshold)
        risk_input_values = _risk_input_values(Path(args.risk_input)) if args.risk_input else {}
        risk_input_values["broad_market_drop_gt_3pct_count"] = quote_stats["drop_count"]
        risk_input = RiskInput(**risk_input_values)
        limits = RiskLimits(
            max_position_weight=args.max_position_weight,
            max_portfolio_drawdown=args.max_portfolio_drawdown,
            max_single_position_drawdown=args.max_single_position_drawdown,
            max_goodwill_ratio=args.max_goodwill_ratio,
            max_pledge_ratio=args.max_pledge_ratio,
            max_main_outflow_days=args.max_main_outflow_days,
            broad_market_drop_threshold=args.broad_market_drop_threshold,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    evaluation = evaluate_risk(risk_input, limits)
    quote_stats_payload = {
        "quotes": str(Path(args.quotes)),
        "drop_threshold": args.drop_threshold,
        "drop_count": quote_stats["drop_count"],
        "drop_ratio": _drop_ratio(quote_stats["drop_count"], quote_stats["valid_rows"]),
        "valid_rows": quote_stats["valid_rows"],
        "skipped_rows": quote_stats["skipped_rows"],
    }
    payload = {
        "metadata": {
            "evaluated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "risk_input": str(Path(args.risk_input)) if args.risk_input else None,
        },
        "risk_input": asdict(risk_input),
        "limits": asdict(limits),
        "quote_stats": quote_stats_payload,
        "valid_quote_rows": quote_stats["valid_rows"],
        "skipped_quote_rows": quote_stats["skipped_rows"],
        "action": evaluation.action.value,
        "warnings": [
            {
                "layer": warning.layer,
                "rule": warning.rule,
                "action": warning.action.value,
                "message": warning.message,
                "observed_value": warning.observed_value,
                "threshold_value": warning.threshold_value,
            }
            for warning in evaluation.warnings
        ],
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"risk_action={evaluation.action.value}")
    print(f"broad_market_drop_gt_3pct_count={risk_input.broad_market_drop_gt_3pct_count}")
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


def _risk_input_values(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Risk input JSON must be an object")
    allowed_fields = {field.name for field in fields(RiskInput)}
    unknown_fields = sorted(set(payload) - allowed_fields)
    if unknown_fields:
        raise ValueError(f"Unknown risk input fields: {', '.join(unknown_fields)}")
    return {
        name: _coerce_risk_input_value(name, value)
        for name, value in payload.items()
        if name != "broad_market_drop_gt_3pct_count"
    }


_FLOAT_RISK_INPUT_FIELDS = {
    "position_weight",
    "portfolio_drawdown",
    "single_position_drawdown",
    "goodwill_ratio",
    "pledge_ratio",
}
_INT_RISK_INPUT_FIELDS = {
    "negative_event_count",
    "main_outflow_days",
    "broad_market_drop_gt_3pct_count",
}
_BOOL_RISK_INPUT_FIELDS = {"st_warning", "index_below_annual_ma"}


def _coerce_risk_input_value(name: str, value: object) -> object:
    if name in _FLOAT_RISK_INPUT_FIELDS:
        return _non_negative_float(name, value)
    if name in _INT_RISK_INPUT_FIELDS:
        return _non_negative_int(name, value)
    if name in _BOOL_RISK_INPUT_FIELDS:
        return _bool_value(name, value)
    return value


def _non_negative_float(name: str, value: object) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        number = _float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be a non-negative number")
    return number


def _non_negative_int(name: str, value: object) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError(f"{name} must be an integer")
        number = int(value)
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped.isdigit():
            raise ValueError(f"{name} must be an integer")
        number = int(stripped)
    else:
        raise ValueError(f"{name} must be an integer")
    if number < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return number


def _bool_value(name: str, value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise ValueError(f"{name} must be a boolean")


def _drop_ratio(drop_count: int, valid_rows: int) -> float:
    if valid_rows == 0:
        return 0.0
    return round(drop_count / valid_rows, 6)


def _float(value: object) -> float:
    return float(str(value).replace(",", "").strip())


if __name__ == "__main__":
    raise SystemExit(main())
