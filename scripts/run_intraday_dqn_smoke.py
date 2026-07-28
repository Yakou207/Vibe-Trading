"""SMOKE TEST for the intraday linear-Q policy — NO profit conclusions.

40 days of Sina 5-minute data is far too small for any RL performance claim
(and the recent test windows are contaminated by the V3 reversion experiment).
This harness only verifies, per the agreed protocol:

  1. training runs and the loss/PnL trace is finite;
  2. every evaluated day is T+1-legal and ends flat-to-base;
  3. the greedy policy actually trades (repo lesson: daily DQN barely traded);
  4. behaviour across seeds (trade counts, PnL spread) — divergence is the
     other recorded failure mode.

Formal acceptance re-runs this walk-forward style on >=250 days of Tushare
minute data, untouched by any prior experiment.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.data import normalize_a_share_symbol  # noqa: E402
from fintech_quant.intraday.minute_data import (  # noqa: E402
    bars_by_day,
    drop_corporate_action_days,
    load_minute_bars_csv,
)
from fintech_quant.intraday.rl_policy import (  # noqa: E402
    LinearQConfig,
    run_policy_day,
    train_intraday_linear_q,
)
from fintech_quant.intraday.rotation import RotationParams  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Intraday linear-Q smoke run (no profit conclusions).")
    parser.add_argument("--data-dir", default="data/raw/intraday_5min")
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--base-notional", type=float, default=8000.0)
    parser.add_argument("--train-days", type=int, default=25)
    parser.add_argument("--seeds", default="0,1,2")
    parser.add_argument("--episodes", type=int, default=30)
    parser.add_argument("--output", default="outputs/intraday_v3/linear_q_smoke.json")
    args = parser.parse_args()

    params = RotationParams()
    symbols = [normalize_a_share_symbol(s.strip()) for s in args.symbols.split(",")]
    per_symbol_days: dict[str, dict[str, list[dict[str, object]]]] = {}
    for symbol in symbols:
        days = drop_corporate_action_days(
            bars_by_day(load_minute_bars_csv(Path(args.data_dir) / f"{symbol}.csv"))
        )
        per_symbol_days[symbol] = {d: b for d, b in days.items() if len(b) >= 40}

    all_days = sorted(set().union(*[set(d) for d in per_symbol_days.values()]))
    train_days = all_days[: args.train_days]
    eval_days = all_days[args.train_days :]

    def episodes_for(day_list):
        out = []
        for symbol, days in per_symbol_days.items():
            for day in day_list:
                bars = days.get(day)
                if bars:
                    shares = int(args.base_notional // float(bars[0]["open"]) // 100 * 100)
                    if shares > 0:
                        out.append((symbol, bars, shares))
        return out

    train_set = episodes_for(train_days)
    eval_set = episodes_for(eval_days)
    config = LinearQConfig(episodes=args.episodes)

    seed_reports = []
    for seed in [int(s) for s in args.seeds.split(",")]:
        run = train_intraday_linear_q(train_set, params=params, config=config, seed=seed)
        greedy = run.policy.act
        evaluation = {"trades": 0, "rounds": 0, "net_pnl": 0.0, "unbalanced_days": 0}
        for _symbol, bars, shares in eval_set:
            result = run_policy_day(bars, base_shares=shares, policy=greedy, params=params)
            evaluation["trades"] += len(result.trades)
            evaluation["rounds"] += result.rounds
            evaluation["net_pnl"] = round(evaluation["net_pnl"] + result.enhancement_pnl, 2)
            evaluation["unbalanced_days"] += 0 if result.end_shares_match_base else 1
        seed_reports.append(
            {
                "seed": run.seed,
                "episode_pnl_first": run.episode_pnls[0],
                "episode_pnl_last": run.episode_pnls[-1],
                "all_finite": all(abs(p) < 1e12 for p in run.episode_pnls),
                "eval": evaluation,
            }
        )

    trade_counts = [r["eval"]["trades"] for r in seed_reports]
    report = {
        "kind": "v3_linear_q_smoke",
        "verdict_scope": "SMOKE ONLY — profitability numbers are NOT evidence (40-day contaminated window)",
        "symbols": symbols,
        "train_days": len(train_days),
        "eval_days": len(eval_days),
        "seeds": seed_reports,
        "checks": {
            "training_finite": all(r["all_finite"] for r in seed_reports),
            "legality_clean": all(r["eval"]["unbalanced_days"] == 0 for r in seed_reports),
            "policy_trades": all(t > 0 for t in trade_counts),
            "seed_trade_counts": trade_counts,
            "seed_trade_count_spread": max(trade_counts) - min(trade_counts) if trade_counts else 0,
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["checks"], indent=2))
    for row in seed_reports:
        print(f"seed={row['seed']} eval={row['eval']} ep_pnl {row['episode_pnl_first']} -> {row['episode_pnl_last']}")
    print(f"output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
