from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pandas as pd

from fintech_quant.training.dqn import DQNConfig, train_dqn_run
from fintech_quant.training.dqn_checkpoint import (
    load_latest_dqn_checkpoint,
    save_dqn_checkpoint,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run resumable DQN continual training.")
    parser.add_argument("--features-csv", default="data/processed/akshare_research_features.csv")
    parser.add_argument("--checkpoint-root", default="data/models/dqn")
    parser.add_argument("--checkpoint-id", default="")
    parser.add_argument("--resume", default="none", choices=["none", "latest"])
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--max-checkpoints", type=int, default=10)
    parser.add_argument("--episodes", type=int, default=5)
    parser.add_argument("--gamma", type=float, default=0.95)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--epsilon", type=float, default=0.2)
    parser.add_argument("--min-epsilon", type=float, default=0.05)
    parser.add_argument("--epsilon-decay", type=float, default=0.95)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--replay-capacity", type=int, default=10_000)
    parser.add_argument("--target-update-interval", type=int, default=100)
    parser.add_argument("--trade-penalty", type=float, default=0.0005)
    parser.add_argument("--drawdown-penalty", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    features = pd.read_csv(args.features_csv)
    if features.empty:
        raise ValueError("DQN continual training features must not be empty.")

    checkpoint_root = Path(args.checkpoint_root)
    initial_run = None
    resume_mode = "fresh" if args.fresh else args.resume
    if resume_mode == "latest":
        initial_run = load_latest_dqn_checkpoint(checkpoint_root)

    config = DQNConfig(
        episodes=args.episodes,
        gamma=args.gamma,
        learning_rate=args.learning_rate,
        epsilon=args.epsilon,
        min_epsilon=args.min_epsilon,
        epsilon_decay=args.epsilon_decay,
        batch_size=args.batch_size,
        replay_capacity=args.replay_capacity,
        target_update_interval=args.target_update_interval,
        trade_penalty=args.trade_penalty,
        drawdown_penalty=args.drawdown_penalty,
        seed=args.seed,
    )
    run = train_dqn_run(features, config, initial_run=initial_run)
    train_dates = pd.to_datetime(features["date"]).dt.date
    metadata = {
        "source": str(args.features_csv),
        "resume_mode": resume_mode,
        "train_start": train_dates.min().isoformat(),
        "train_end": train_dates.max().isoformat(),
        "train_rows": len(features),
        "git_commit": _git_commit(),
    }
    metrics = {
        "episodes_trained": run.episodes_trained,
        "training_steps": run.model.training_steps,
        "replay_size": len(run.replay),
        "feature_count": len(run.model.scaler.columns),
    }
    checkpoint_path = save_dqn_checkpoint(
        run,
        checkpoint_root=checkpoint_root,
        checkpoint_id=args.checkpoint_id or None,
        metadata=metadata,
        metrics=metrics,
        max_checkpoints=args.max_checkpoints,
    )
    print(
        json.dumps(
            {
                "checkpoint": str(checkpoint_path),
                "resume_mode": resume_mode,
                **metrics,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
