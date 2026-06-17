from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from fintech_quant.reports.strategy_comparison import run_strategy_comparison_report
from fintech_quant.training.dqn import DQNConfig
from fintech_quant.training.q_learning import QLearningConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="Run strategy comparison diagnostics report.")
    parser.add_argument("--features-csv", default="data/processed/akshare_research_features.csv")
    parser.add_argument("--output", default="outputs/strategy_comparison_report.json")
    parser.add_argument("--train-years", type=int, default=2)
    parser.add_argument("--test-years", type=int, default=1)
    parser.add_argument("--episodes", type=int, default=25)
    parser.add_argument("--dqn-episodes", type=int, default=3)
    parser.add_argument("--alpha", type=float, default=0.1)
    parser.add_argument("--gamma", type=float, default=0.95)
    parser.add_argument("--dqn-gamma", type=float, default=0.95)
    parser.add_argument("--dqn-learning-rate", type=float, default=0.001)
    parser.add_argument("--epsilon", type=float, default=0.2)
    parser.add_argument("--dqn-epsilon", type=float, default=0.2)
    parser.add_argument("--min-epsilon", type=float, default=0.05)
    parser.add_argument("--dqn-min-epsilon", type=float, default=0.05)
    parser.add_argument("--epsilon-decay", type=float, default=0.95)
    parser.add_argument("--dqn-epsilon-decay", type=float, default=0.95)
    parser.add_argument("--dqn-batch-size", type=int, default=64)
    parser.add_argument("--dqn-replay-capacity", type=int, default=10000)
    parser.add_argument("--dqn-target-update-interval", type=int, default=100)
    parser.add_argument("--trade-penalty", type=float, default=0.0005)
    parser.add_argument("--dqn-trade-penalty", type=float, default=0.0005)
    parser.add_argument("--dqn-drawdown-penalty", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dqn-seed", type=int, default=42)
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    parser.add_argument("--target-weight", type=float, default=0.03)
    parser.add_argument("--max-position-weight", type=float, default=0.05)
    parser.add_argument("--max-portfolio-drawdown", type=float, default=0.2)
    parser.add_argument("--commission-rate", type=float, default=0.0003)
    parser.add_argument("--stamp-tax-rate", type=float, default=0.001)
    parser.add_argument("--slippage-rate", type=float, default=0.0005)
    args = parser.parse_args()

    report = run_strategy_comparison_report(
        features=pd.read_csv(args.features_csv),
        q_config=QLearningConfig(
            episodes=args.episodes,
            alpha=args.alpha,
            gamma=args.gamma,
            epsilon=args.epsilon,
            min_epsilon=args.min_epsilon,
            epsilon_decay=args.epsilon_decay,
            trade_penalty=args.trade_penalty,
            seed=args.seed,
        ),
        dqn_config=DQNConfig(
            episodes=args.dqn_episodes,
            gamma=args.dqn_gamma,
            learning_rate=args.dqn_learning_rate,
            epsilon=args.dqn_epsilon,
            min_epsilon=args.dqn_min_epsilon,
            epsilon_decay=args.dqn_epsilon_decay,
            batch_size=args.dqn_batch_size,
            replay_capacity=args.dqn_replay_capacity,
            target_update_interval=args.dqn_target_update_interval,
            trade_penalty=args.dqn_trade_penalty,
            drawdown_penalty=args.dqn_drawdown_penalty,
            seed=args.dqn_seed,
        ),
        train_years=args.train_years,
        test_years=args.test_years,
        initial_cash=args.initial_cash,
        target_weight=args.target_weight,
        max_position_weight=args.max_position_weight,
        max_portfolio_drawdown=args.max_portfolio_drawdown,
        commission_rate=args.commission_rate,
        stamp_tax_rate=args.stamp_tax_rate,
        slippage_rate=args.slippage_rate,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"windows": len(report["windows"]), "output": str(output_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
