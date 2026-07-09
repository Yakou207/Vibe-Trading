from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Mapping


FIELDS = ("symbol", "target_weight", "score", "score_confidence", "rl_action", "reason")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate paper-trading target weights from a research run report.")
    parser.add_argument("--report", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output", default="outputs/paper_trading/targets.csv")
    parser.add_argument("--buy-threshold", type=float, default=70.0)
    parser.add_argument("--min-score-confidence", type=float, default=0.8)
    parser.add_argument("--max-position-weight", type=float, default=0.08)
    parser.add_argument("--max-targets", type=int, default=None)
    parser.add_argument("--rl-signals", default=None, help="Optional CSV with symbol,trade_date,rl_action.")
    args = parser.parse_args()

    report = _load_json(Path(args.report))
    targets = generate_targets(
        report,
        as_of=args.as_of,
        buy_threshold=args.buy_threshold,
        min_score_confidence=args.min_score_confidence,
        max_position_weight=args.max_position_weight,
        max_targets=args.max_targets,
        rl_signals=_load_rl_signals(Path(args.rl_signals), args.as_of) if args.rl_signals else {},
    )
    _write_targets(Path(args.output), targets)
    print(f"target_count={len(targets)}")
    print(f"output={args.output}")
    return 0


def generate_targets(
    report: Mapping[str, object],
    *,
    as_of: str,
    buy_threshold: float,
    min_score_confidence: float,
    max_position_weight: float,
    max_targets: int | None,
    rl_signals: Mapping[str, str],
) -> list[dict[str, object]]:
    blocked = _blocked_symbols(report, as_of)
    candidates = []
    for score in report.get("scores", []):
        if not isinstance(score, Mapping) or score.get("trade_date") != as_of:
            continue
        symbol = str(score["symbol"])
        total = float(score["total"])
        confidence = float(score["confidence"])
        if symbol in blocked or total < buy_threshold or confidence < min_score_confidence:
            continue
        rl_action = rl_signals.get(symbol, "buy")
        target_weight = _overlay_weight(max_position_weight, rl_action)
        if target_weight <= 0:
            continue
        candidates.append(
            {
                "symbol": symbol,
                "target_weight": round(target_weight, 6),
                "score": round(total, 6),
                "score_confidence": round(confidence, 6),
                "rl_action": rl_action,
                "reason": f"score={total:.2f}; confidence={confidence:.2f}; rl_action={rl_action}",
            }
        )
    candidates.sort(key=lambda row: (-float(row["score"]), str(row["symbol"])))
    if max_targets is not None:
        if max_targets <= 0:
            raise ValueError("max_targets must be positive")
        candidates = candidates[:max_targets]
    return candidates


def _blocked_symbols(report: Mapping[str, object], as_of: str) -> set[str]:
    blocked = set()
    for warning in report.get("risk_warnings", []):
        if not isinstance(warning, Mapping) or warning.get("trade_date") != as_of:
            continue
        if str(warning.get("action")) in {"reduce", "liquidate"}:
            blocked.add(str(warning["symbol"]))
    return blocked


def _overlay_weight(max_position_weight: float, rl_action: str) -> float:
    action = rl_action.strip().lower()
    if action == "buy":
        return max_position_weight
    if action == "hold":
        return max_position_weight * 0.5
    if action == "sell":
        return 0.0
    raise ValueError(f"unsupported rl_action: {rl_action!r}")


def _load_rl_signals(path: Path, as_of: str) -> dict[str, str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {
            str(row["symbol"]): str(row["rl_action"])
            for row in csv.DictReader(handle)
            if row.get("trade_date") == as_of
        }


def _write_targets(path: Path, targets: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(targets)


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
