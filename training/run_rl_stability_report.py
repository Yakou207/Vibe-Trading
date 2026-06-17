from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from fintech_quant.reports.rl_stability import render_rl_stability_html, run_rl_stability_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run multi-seed RL stability training report.")
    parser.add_argument("--features-csv", default="data/processed/akshare_research_features.csv")
    parser.add_argument("--output-json", default="outputs/rl_stability_report.json")
    parser.add_argument("--output-html", default="outputs/rl_stability_report.html")
    parser.add_argument("--seeds", default="1,7,42")
    parser.add_argument("--episodes", default="25,50,100,200")
    parser.add_argument("--train-years", type=int, default=2)
    parser.add_argument("--test-years", type=int, default=1)
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    parser.add_argument("--target-weight", type=float, default=0.03)
    parser.add_argument("--max-position-weight", type=float, default=0.05)
    parser.add_argument("--max-portfolio-drawdown", type=float, default=0.2)
    parser.add_argument("--commission-rate", type=float, default=0.0003)
    parser.add_argument("--stamp-tax-rate", type=float, default=0.001)
    parser.add_argument("--slippage-rate", type=float, default=0.0005)
    parser.add_argument("--alpha", type=float, default=0.1)
    parser.add_argument("--gamma", type=float, default=0.95)
    parser.add_argument("--epsilon", type=float, default=0.2)
    parser.add_argument("--min-epsilon", type=float, default=0.05)
    parser.add_argument("--epsilon-decay", type=float, default=0.95)
    parser.add_argument("--trade-penalty", type=float, default=0.0005)
    parser.add_argument("--drawdown-penalty", type=float, default=0.2)
    args = parser.parse_args()

    report = run_rl_stability_report(
        features=pd.read_csv(args.features_csv),
        seeds=_parse_ints(args.seeds),
        episode_counts=_parse_ints(args.episodes),
        train_years=args.train_years,
        test_years=args.test_years,
        initial_cash=args.initial_cash,
        target_weight=args.target_weight,
        max_position_weight=args.max_position_weight,
        max_portfolio_drawdown=args.max_portfolio_drawdown,
        commission_rate=args.commission_rate,
        stamp_tax_rate=args.stamp_tax_rate,
        slippage_rate=args.slippage_rate,
        alpha=args.alpha,
        gamma=args.gamma,
        epsilon=args.epsilon,
        min_epsilon=args.min_epsilon,
        epsilon_decay=args.epsilon_decay,
        trade_penalty=args.trade_penalty,
        drawdown_penalty=args.drawdown_penalty,
    )
    json_path = Path(args.output_json)
    html_path = Path(args.output_html)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_rl_stability_html(report), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "html": str(html_path)}, indent=2))
    return 0


def _parse_ints(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
