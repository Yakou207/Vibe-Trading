from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.reports.pnl_curve import build_pnl_curve, write_pnl_curve  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a compact, source-backed CSI 300 PnL curve artifact."
    )
    parser.add_argument("--baseline-report", required=True)
    parser.add_argument("--risk-controlled-report", required=True)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = build_pnl_curve(
        baseline_report=Path(args.baseline_report),
        risk_controlled_report=Path(args.risk_controlled_report),
        benchmark=Path(args.benchmark),
    )
    output = Path(args.output)
    write_pnl_curve(output, payload)
    print(f"pnl_curve_path={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
