from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.reports.dashboard import build_research_dashboard, load_json, write_dashboard  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a daily quant monitoring dashboard HTML.")
    parser.add_argument("--comparison", required=True)
    parser.add_argument("--walk-forward", default=None)
    parser.add_argument("--paper-report", default=None)
    parser.add_argument("--output", default="outputs/research_dashboard.html")
    args = parser.parse_args()

    html = build_research_dashboard(
        comparison=load_json(Path(args.comparison)),
        walk_forward=load_json(Path(args.walk_forward)) if args.walk_forward else None,
        paper_report=load_json(Path(args.paper_report)) if args.paper_report else None,
    )
    output_path = Path(args.output)
    write_dashboard(output_path, html)
    print(f"dashboard_path={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
