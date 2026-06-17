from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from fintech_quant.features.factor_diagnostics import factor_diagnostics
from fintech_quant.features.factor_library import available_factor_specs, factor_names
from fintech_quant.reports.factor_report import build_factor_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run factor diagnostics report.")
    parser.add_argument("--features-csv", default="data/processed/akshare_research_features.csv")
    parser.add_argument("--output", default="outputs/factor_diagnostics_report.json")
    args = parser.parse_args()

    features = pd.read_csv(args.features_csv)
    specs = available_factor_specs(features)
    diagnostics = factor_diagnostics(features, factor_names(specs), factor_specs=specs)
    report = build_factor_report(diagnostics)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"factors": report["factor_count"], "output": str(output_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
