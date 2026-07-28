"""Walk-forward backtest of the V3 intraday T+0 rotation (see design doc).

Per fold: pick z_enter on the train days (net enhancement PnL), evaluate on the
test days untouched. Baseline is hold-only, so every reported number is the
incremental (enhancement) PnL net of commissions, stamp duty, and slippage.
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
from fintech_quant.intraday.rotation import RotationParams, run_rotation_day  # noqa: E402

Z_ENTER_GRID = (1.5, 2.0, 2.5)


def main() -> int:
    parser = argparse.ArgumentParser(description="Walk-forward V3 rotation backtest.")
    parser.add_argument("--data-dir", default="data/raw/intraday_5min")
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--base-notional", type=float, default=8000.0, help="Base position value per symbol (CNY).")
    parser.add_argument("--train-days", type=int, default=15)
    parser.add_argument("--test-days", type=int, default=5)
    parser.add_argument("--output", default="outputs/intraday_v3/walkforward_report.json")
    args = parser.parse_args()

    symbols = [normalize_a_share_symbol(s.strip()) for s in args.symbols.split(",")]
    days_by_symbol = {}
    for symbol in symbols:
        days = drop_corporate_action_days(
            bars_by_day(load_minute_bars_csv(Path(args.data_dir) / f"{symbol}.csv"))
        )
        # Partial first/last sessions (Sina window edges) would distort VWAP.
        days_by_symbol[symbol] = {d: bars for d, bars in days.items() if len(bars) >= 40}

    all_days = sorted(set().union(*[set(d) for d in days_by_symbol.values()]))
    folds = []
    start = 0
    while start + args.train_days + args.test_days <= len(all_days):
        train = all_days[start : start + args.train_days]
        test = all_days[start + args.train_days : start + args.train_days + args.test_days]
        folds.append((train, test))
        start += args.test_days

    if not folds:
        raise SystemExit(f"not enough days ({len(all_days)}) for one fold")

    fold_reports = []
    for train, test in folds:
        train_by_z = {
            z: _run_span(days_by_symbol, train, z, args.base_notional) for z in Z_ENTER_GRID
        }
        best_z = max(Z_ENTER_GRID, key=lambda z: train_by_z[z]["net_pnl"])
        test_result = _run_span(days_by_symbol, test, best_z, args.base_notional)
        fold_reports.append(
            {
                "train_span": [train[0], train[-1]],
                "test_span": [test[0], test[-1]],
                "train_net_pnl_by_z": {str(z): train_by_z[z]["net_pnl"] for z in Z_ENTER_GRID},
                "chosen_z_enter": best_z,
                "test": test_result,
            }
        )

    total_test_pnl = round(sum(f["test"]["net_pnl"] for f in fold_reports), 2)
    total_test_trades = sum(f["test"]["trades"] for f in fold_reports)
    positive_folds = sum(1 for f in fold_reports if f["test"]["net_pnl"] >= 0)
    report = {
        "kind": "v3_rotation_walkforward",
        "symbols": symbols,
        "base_notional_per_symbol": args.base_notional,
        "days_available": len(all_days),
        "folds": fold_reports,
        "summary": {
            "total_test_net_pnl": total_test_pnl,
            "total_test_trades": total_test_trades,
            "total_test_costs": round(sum(f["test"]["costs"] for f in fold_reports), 2),
            "total_test_gross_pnl": round(sum(f["test"]["gross_pnl"] for f in fold_reports), 2),
            "positive_test_folds": f"{positive_folds}/{len(fold_reports)}",
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    for fold in fold_reports:
        print(
            f"fold test {fold['test_span'][0]}..{fold['test_span'][-1]} "
            f"z={fold['chosen_z_enter']} net={fold['test']['net_pnl']} trades={fold['test']['trades']}"
        )
    print(f"output={output}")
    return 0


def _run_span(days_by_symbol, days, z_enter, base_notional) -> dict[str, object]:
    params = RotationParams(z_enter=z_enter)
    net = gross = costs = 0.0
    trades = rounds = 0
    illegal = 0
    for symbol, symbol_days in days_by_symbol.items():
        for day in days:
            bars = symbol_days.get(day)
            if not bars:
                continue
            base_shares = int(base_notional // float(bars[0]["open"]) // 100 * 100)
            result = run_rotation_day(bars, base_shares=base_shares, params=params)
            net += result.enhancement_pnl
            gross += result.enhancement_pnl + result.total_cost
            costs += result.total_cost
            trades += len(result.trades)
            rounds += result.rounds
            if not result.end_shares_match_base:
                illegal += 1
    return {
        "net_pnl": round(net, 2),
        "gross_pnl": round(gross, 2),
        "costs": round(costs, 2),
        "trades": trades,
        "rounds": rounds,
        "unbalanced_days": illegal,
    }


if __name__ == "__main__":
    raise SystemExit(main())
