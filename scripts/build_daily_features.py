from __future__ import annotations

import argparse
from pathlib import Path

from fintech_quant.features.indicators import build_daily_feature_frame, feature_columns


def main() -> int:
    parser = argparse.ArgumentParser(description="Build daily technical indicator features.")
    parser.add_argument("--daily-csv", default="data/processed/akshare_research_daily.csv")
    parser.add_argument("--output", default="data/processed/akshare_research_features.csv")
    args = parser.parse_args()

    import pandas as pd

    daily = pd.read_csv(args.daily_csv)
    features = build_daily_feature_frame(daily)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    features.to_csv(output_path, index=False)
    print(
        f"Wrote {len(features)} rows, {features['代码'].nunique()} symbols, "
        f"{len(feature_columns())} feature columns to {output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
