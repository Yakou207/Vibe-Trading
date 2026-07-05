from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.reports import compare_strategy_reports, write_comparison_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare baseline and candidate A-share research reports.")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", default="outputs/research_runs/comparison.json")
    parser.add_argument("--walk-forward-segments", type=int, default=4)
    parser.add_argument("--align-to-candidate", action="store_true")
    args = parser.parse_args()

    comparison = compare_strategy_reports(
        _load_json(Path(args.baseline)),
        _load_json(Path(args.candidate)),
        walk_forward_segments=args.walk_forward_segments,
        align_to_candidate=args.align_to_candidate,
    )
    output_path = Path(args.output)
    write_comparison_report(output_path, comparison)
    print(f"comparison_path={output_path}")
    print(f"candidate_total_return={comparison.candidate.total_return}")
    print(f"baseline_total_return={comparison.baseline.total_return}")
    print(f"excess_return={comparison.excess_return}")
    print(f"aligned_to_candidate={args.align_to_candidate}")
    return 0


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
