from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.training import (  # noqa: E402
    TorchDQNConfig,
    load_rl_state_jsonl,
    train_linear_dqn_policy_report,
    train_torch_dqn_policy_report,
    write_dqn_policy_report,
)
from fintech_quant.backtesting import DrawdownControlPolicy  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Train a DQN policy on the RL state dataset.")
    parser.add_argument(
        "--input", required=True, help="RL state JSONL produced by scripts/build_rl_dataset.py."
    )
    parser.add_argument("--output", default="outputs/research_runs/linear_q_dqn/run_report.json")
    parser.add_argument("--backend", choices=("linear", "torch"), default="torch")
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--learning-rate", type=float, default=None)
    parser.add_argument("--gamma", type=float, default=None)
    parser.add_argument("--transaction-cost", type=float, default=None)
    parser.add_argument("--drawdown-penalty", type=float, default=None)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--train-frequency", type=int, default=4)
    parser.add_argument(
        "--eval-start", default=None, help="First trade date used for out-of-sample evaluation."
    )
    parser.add_argument("--run-id", default="linear-q-dqn")
    parser.add_argument("--no-drawdown-control", action="store_true")
    args = parser.parse_args()
    defaults = (
        {
            "epochs": 5,
            "learning_rate": 0.001,
            "gamma": 0.95,
            "transaction_cost": 0.001,
            "drawdown_penalty": 0.5,
        }
        if args.backend == "torch"
        else {
            "epochs": 50,
            "learning_rate": 0.05,
            "gamma": 0.0,
            "transaction_cost": 0.0,
            "drawdown_penalty": 0.0,
        }
    )
    epochs = args.epochs if args.epochs is not None else int(defaults["epochs"])
    learning_rate = (
        args.learning_rate if args.learning_rate is not None else float(defaults["learning_rate"])
    )
    gamma = args.gamma if args.gamma is not None else float(defaults["gamma"])
    transaction_cost = (
        args.transaction_cost
        if args.transaction_cost is not None
        else float(defaults["transaction_cost"])
    )
    drawdown_penalty = (
        args.drawdown_penalty
        if args.drawdown_penalty is not None
        else float(defaults["drawdown_penalty"])
    )

    try:
        samples = load_rl_state_jsonl(Path(args.input))
        if args.backend == "torch":
            if args.eval_start:
                raise ValueError("torch backend does not support --eval-start yet")
            report = train_torch_dqn_policy_report(
                samples,
                run_id=args.run_id,
                symbol=args.symbol,
                config=TorchDQNConfig(
                    episodes=epochs,
                    learning_rate=learning_rate,
                    gamma=gamma,
                    transaction_cost=transaction_cost,
                    drawdown_penalty=drawdown_penalty,
                    batch_size=args.batch_size,
                    train_frequency=args.train_frequency,
                ),
                drawdown_policy=None if args.no_drawdown_control else DrawdownControlPolicy(),
            )
        else:
            report = train_linear_dqn_policy_report(
                samples,
                run_id=args.run_id,
                symbol=args.symbol,
                epochs=epochs,
                learning_rate=learning_rate,
                gamma=gamma,
                transaction_cost=transaction_cost,
                drawdown_penalty=drawdown_penalty,
                eval_start=date.fromisoformat(args.eval_start) if args.eval_start else None,
                drawdown_policy=None if args.no_drawdown_control else DrawdownControlPolicy(),
            )
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    output_path = Path(args.output)
    write_dqn_policy_report(output_path, report)
    print(f"report_path={output_path}")
    print(f"policy={report['strategy_config']['policy']}")
    print(f"symbol={report['strategy_config']['symbol']}")
    print(f"backend={args.backend}")
    print(f"eval_start={report['strategy_config'].get('eval_start')}")
    print(f"drawdown_penalty={report['strategy_config']['drawdown_penalty']}")
    print(f"train_sample_count={report['strategy_config'].get('train_sample_count')}")
    print(f"eval_sample_count={report['strategy_config'].get('eval_sample_count')}")
    print(f"ending_equity={report['summary']['ending_equity']}")
    print(f"total_return={report['summary']['total_return']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
