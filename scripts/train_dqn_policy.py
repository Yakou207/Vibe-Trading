from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.training import (  # noqa: E402
    load_rl_state_jsonl,
    train_linear_dqn_policy_report,
    write_dqn_policy_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Train a lightweight linear Q policy on the RL state dataset.")
    parser.add_argument("--input", required=True, help="RL state JSONL produced by scripts/build_rl_dataset.py.")
    parser.add_argument("--output", default="outputs/research_runs/linear_q_dqn/run_report.json")
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--gamma", type=float, default=0.0)
    parser.add_argument("--transaction-cost", type=float, default=0.0)
    parser.add_argument("--run-id", default="linear-q-dqn")
    args = parser.parse_args()

    try:
        report = train_linear_dqn_policy_report(
            load_rl_state_jsonl(Path(args.input)),
            run_id=args.run_id,
            symbol=args.symbol,
            epochs=args.epochs,
            learning_rate=args.learning_rate,
            gamma=args.gamma,
            transaction_cost=args.transaction_cost,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    output_path = Path(args.output)
    write_dqn_policy_report(output_path, report)
    print(f"report_path={output_path}")
    print(f"policy={report['strategy_config']['policy']}")
    print(f"symbol={report['strategy_config']['symbol']}")
    print(f"ending_equity={report['summary']['ending_equity']}")
    print(f"total_return={report['summary']['total_return']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
