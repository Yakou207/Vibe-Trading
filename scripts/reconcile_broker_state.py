from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.execution.broker import reconcile_broker_state  # noqa: E402
from fintech_quant.execution.paper_account import load_paper_account  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile a QMT bridge broker-state export against the canonical paper account."
    )
    parser.add_argument("--account", required=True)
    parser.add_argument("--broker-state", required=True)
    parser.add_argument("--output", default=None)
    parser.add_argument("--cash-tolerance", type=float, default=100.0)
    parser.add_argument("--initial-cash", type=float, default=100000.0)
    args = parser.parse_args()

    account = load_paper_account(Path(args.account), initial_cash=args.initial_cash)
    broker_state = json.loads(Path(args.broker_state).read_text(encoding="utf-8"))
    report = reconcile_broker_state(
        account,
        broker_state,
        cash_tolerance=args.cash_tolerance,
    )
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"output={output}")
    print(f"status={report['status']} differences={len(report['differences'])}")
    if report["differences"]:
        print(json.dumps(report["differences"], ensure_ascii=False))
    return 0 if report["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
