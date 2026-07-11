from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.training import (  # noqa: E402
    TorchDQNConfig,
    load_rl_state_jsonl,
    run_torch_dqn_walk_forward_report,
    write_dqn_walk_forward_report,
)
from fintech_quant.backtesting import DrawdownControlPolicy  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PyTorch DQN rolling walk-forward validation.")
    parser.add_argument("--input", required=True, help="RL state JSONL produced by scripts/build_rl_dataset.py.")
    parser.add_argument("--output", default="outputs/research_runs/torch_dqn_walk_forward/report.json")
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--train-years", type=int, default=2)
    parser.add_argument("--eval-years", type=int, default=1)
    parser.add_argument("--episodes", type=int, default=5)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--gamma", type=float, default=0.95)
    parser.add_argument("--epsilon", type=float, default=0.2)
    parser.add_argument("--min-epsilon", type=float, default=0.05)
    parser.add_argument("--epsilon-decay", type=float, default=0.95)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--transaction-cost", type=float, default=0.0)
    parser.add_argument("--drawdown-penalty", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--run-id", default="torch-dqn-walk-forward")
    parser.add_argument("--no-drawdown-control", action="store_true")
    args = parser.parse_args()

    try:
        report = run_torch_dqn_walk_forward_report(
            load_rl_state_jsonl(Path(args.input)),
            run_id=args.run_id,
            symbol=args.symbol,
            train_years=args.train_years,
            eval_years=args.eval_years,
            config=TorchDQNConfig(
                episodes=args.episodes,
                learning_rate=args.learning_rate,
                gamma=args.gamma,
                epsilon=args.epsilon,
                min_epsilon=args.min_epsilon,
                epsilon_decay=args.epsilon_decay,
                batch_size=args.batch_size,
                transaction_cost=args.transaction_cost,
                drawdown_penalty=args.drawdown_penalty,
                seed=args.seed,
            ),
            drawdown_policy=None if args.no_drawdown_control else DrawdownControlPolicy(),
        )
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    output_path = Path(args.output)
    write_dqn_walk_forward_report(output_path, report)
    print(f"report_path={output_path}")
    print(f"policy={report['policy']}")
    print(f"window_count={report['summary']['window_count']}")
    print(f"mean_total_return={report['summary']['mean_total_return']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
