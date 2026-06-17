from __future__ import annotations

import argparse
import json
from pathlib import Path

from fintech_quant.reports.research_dashboard import render_research_dashboard


def main() -> int:
    parser = argparse.ArgumentParser(description="Build local quant research dashboard HTML.")
    parser.add_argument("--strategy-report", default="outputs/strategy_comparison_report.json")
    parser.add_argument("--factor-report", default="outputs/factor_diagnostics_report.json")
    parser.add_argument("--data-quality-report", default="outputs/data_quality_report.json")
    parser.add_argument("--output", default="outputs/research_dashboard.html")
    args = parser.parse_args()

    strategy_report = _read_json(Path(args.strategy_report))
    factor_report = _read_json(Path(args.factor_report))
    data_quality_report = _read_json(Path(args.data_quality_report), required=False)
    html = render_research_dashboard(strategy_report, factor_report, data_quality_report)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(json.dumps({"output": str(output_path)}, indent=2))
    return 0


def _read_json(path: Path, required: bool = True) -> dict[str, object]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Missing dashboard input: {path}")
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
