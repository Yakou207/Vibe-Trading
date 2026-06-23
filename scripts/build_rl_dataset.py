from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.research.dataset import load_research_dataset  # noqa: E402
from fintech_quant.training import build_rl_state_samples, write_rl_state_jsonl  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic RL state dataset from A-share research inputs.")
    parser.add_argument("--features", required=True)
    parser.add_argument("--universe", required=True)
    parser.add_argument("--information", default=None)
    parser.add_argument("--fundamentals", default=None)
    parser.add_argument("--capital-flow", default=None)
    parser.add_argument("--market-state", default=None)
    parser.add_argument("--output", default="data/processed/rl_state_dataset.jsonl")
    args = parser.parse_args()

    dataset = load_research_dataset(
        Path(args.features),
        Path(args.universe),
        fundamentals_path=_optional_path(args.fundamentals),
        capital_flow_path=_optional_path(args.capital_flow),
        market_state_path=_optional_path(args.market_state),
        information_path=_optional_path(args.information),
    )
    samples = build_rl_state_samples(dataset)
    write_rl_state_jsonl(Path(args.output), samples)
    print(f"samples={len(samples)}")
    print(f"output={args.output}")
    return 0


def _optional_path(value: str | None) -> Path | None:
    return Path(value) if value else None


if __name__ == "__main__":
    raise SystemExit(main())
