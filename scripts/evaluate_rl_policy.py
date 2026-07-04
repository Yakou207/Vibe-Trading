from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.training import evaluate_rl_policy, load_rl_state_jsonl, write_rl_policy_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a simple RL environment policy report.")
    parser.add_argument("--input", required=True, help="RL state JSONL produced by scripts/build_rl_dataset.py.")
    parser.add_argument("--output", default="outputs/research_runs/rl_policy/run_report.json")
    parser.add_argument("--policy", choices=("always_hold", "buy_and_hold"), default="buy_and_hold")
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--transaction-cost", type=float, default=0.0)
    parser.add_argument("--run-id", default="rl-policy-evaluation")
    args = parser.parse_args()

    report = evaluate_rl_policy(
        load_rl_state_jsonl(Path(args.input)),
        policy=args.policy,
        run_id=args.run_id,
        symbol=args.symbol,
        transaction_cost=args.transaction_cost,
    )
    output_path = Path(args.output)
    write_rl_policy_report(output_path, report)
    print(f"report_path={output_path}")
    print(f"policy={report['strategy_config']['policy']}")
    print(f"symbol={report['strategy_config']['symbol']}")
    print(f"ending_equity={report['summary']['ending_equity']}")
    print(f"total_return={report['summary']['total_return']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
