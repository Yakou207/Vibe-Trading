from __future__ import annotations

import argparse
import json
from pathlib import Path

from fintech_quant.strategies.buy_and_hold import evaluate_buy_and_hold
from fintech_quant.training.walk_forward import expanding_windows, rolling_windows


def main() -> int:
    parser = argparse.ArgumentParser(description="Run buy-and-hold walk-forward baseline.")
    parser.add_argument("--features-csv", default="data/processed/akshare_research_features.csv")
    parser.add_argument("--output", default="outputs/walk_forward_buy_hold.json")
    args = parser.parse_args()

    import pandas as pd

    features = pd.read_csv(args.features_csv)
    dates = pd.to_datetime(features["date"])
    windows = [
        *rolling_windows(dates, train_years=2, test_years=1),
        *expanding_windows(dates, initial_train_years=2, test_years=1),
    ]
    results = [
        {
            "window_name": result.window_name,
            "train_start": result.train_start.isoformat(),
            "train_end": result.train_end.isoformat(),
            "test_start": result.test_start.isoformat(),
            "test_end": result.test_end.isoformat(),
            "train_rows": result.train_rows,
            "test_rows": result.test_rows,
            "test_cumulative_return": result.test_cumulative_return,
        }
        for result in (evaluate_buy_and_hold(features, window) for window in windows)
    ]
    payload = {
        "strategy": "buy_and_hold",
        "action_space": ["buy", "sell", "hold"],
        "validation": {
            "rolling": "2 years train, 1 year test",
            "expanding": "initial 2 years train, 1 year test",
            "look_ahead_bias_control": (
                "Features are computed from current and historical rows only; "
                "test returns use target_next_return_1d inside out-of-sample windows."
            ),
        },
        "windows": results,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
