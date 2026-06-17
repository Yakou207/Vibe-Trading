from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import pandas as pd

from fintech_quant.features.indicators import feature_columns
from fintech_quant.training.rl_environment import ACTION_NAMES, AShareBuySellHoldEnvironment


def main() -> int:
    parser = argparse.ArgumentParser(description="Train an initial random buy/sell/hold policy.")
    parser.add_argument("--features-csv", default="data/processed/akshare_research_features.csv")
    parser.add_argument("--output", default="outputs/rl_random_policy_training.json")
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--symbol", default="")
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    parser.add_argument("--target-weight", type=float, default=0.1)
    parser.add_argument("--commission-rate", type=float, default=0.0003)
    parser.add_argument("--stamp-tax-rate", type=float, default=0.001)
    parser.add_argument("--slippage-rate", type=float, default=0.0005)
    args = parser.parse_args()

    features = pd.read_csv(args.features_csv)
    if args.symbol:
        features = features[features["代码"].astype(str) == args.symbol].copy()
    if features.empty:
        raise ValueError("Training features are empty after applying filters.")

    columns = [column for column in feature_columns() if column in features.columns]
    columns = columns or ["close"]
    rng = random.Random(args.seed)
    episode_results = []
    for episode in range(1, args.episodes + 1):
        env = AShareBuySellHoldEnvironment(
            features=features,
            feature_columns=columns,
            initial_cash=args.initial_cash,
            target_weight=args.target_weight,
            commission_rate=args.commission_rate,
            stamp_tax_rate=args.stamp_tax_rate,
            slippage_rate=args.slippage_rate,
        )
        _, info = env.reset()
        total_reward = 0.0
        steps = 0
        terminated = False
        while not terminated:
            _, reward, terminated, truncated, info = env.step(rng.randrange(len(ACTION_NAMES)))
            total_reward += reward
            steps += 1
            if truncated:
                break
        episode_results.append(
            {
                "episode": episode,
                "steps": steps,
                "total_reward": round(total_reward, 10),
                "final_date": info["date"],
                "final_cash": round(float(info["cash"]), 10),
                "final_position_quantity": int(info["position_quantity"]),
            }
        )

    payload = {
        "policy": "random",
        "episodes": args.episodes,
        "seed": args.seed,
        "feature_columns": columns,
        "episode_results": episode_results,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"episodes": args.episodes, "output": str(output_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
