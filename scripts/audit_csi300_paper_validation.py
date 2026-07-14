from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.reports.paper_validation import audit_paper_validation  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit the hash-chained CSI 300 paper-validation evidence."
    )
    parser.add_argument("--anchor", required=True)
    parser.add_argument("--cycle-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--minimum-sessions", type=int, default=40)
    parser.add_argument("--minimum-calendar-days", type=int, default=56)
    parser.add_argument("--maximum-drawdown", type=float, default=0.10)
    args = parser.parse_args()

    cycle_root = Path(args.cycle_root)
    manifests = sorted(cycle_root.glob("*/cycle_manifest.json"))
    report = audit_paper_validation(
        Path(args.anchor),
        manifests,
        minimum_sessions=args.minimum_sessions,
        minimum_calendar_days=args.minimum_calendar_days,
        maximum_drawdown=args.maximum_drawdown,
    )
    output = Path(args.output)
    _write_json_atomic(output, report)
    print(f"validation_report={output}")
    print(f"validation_status={report['status']}")
    print(f"valid_sessions={report['metrics']['valid_sessions']}")
    print("live_trading_enabled=false")
    print("live_trading_authorized=false")
    return 0


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        staged.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        with staged.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(staged, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        staged.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
