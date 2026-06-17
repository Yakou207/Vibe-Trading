from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from fintech_quant.backtesting.engine import BacktestConfig, run_daily_backtest
from fintech_quant.strategies.buy_and_hold import EqualWeightBuyAndHoldStrategy


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real equal-weight buy-and-hold backtest.")
    parser.add_argument("--features-csv", default="data/processed/akshare_research_features.csv")
    parser.add_argument("--output", default="outputs/baseline_backtest.json")
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    parser.add_argument("--target-weight", type=float, default=0.03)
    parser.add_argument("--max-position-weight", type=float, default=0.05)
    parser.add_argument("--max-portfolio-drawdown", type=float, default=0.2)
    parser.add_argument("--commission-rate", type=float, default=0.0003)
    parser.add_argument("--stamp-tax-rate", type=float, default=0.001)
    parser.add_argument("--slippage-rate", type=float, default=0.0005)
    args = parser.parse_args()

    features = pd.read_csv(args.features_csv)
    result = run_daily_backtest(
        features=features,
        strategy=EqualWeightBuyAndHoldStrategy(target_weight=args.target_weight),
        config=BacktestConfig(
            initial_cash=args.initial_cash,
            max_position_weight=args.max_position_weight,
            max_portfolio_drawdown=args.max_portfolio_drawdown,
            commission_rate=args.commission_rate,
            stamp_tax_rate=args.stamp_tax_rate,
            slippage_rate=args.slippage_rate,
        ),
    )
    payload = _result_payload(result)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["metrics"], ensure_ascii=False, indent=2))
    return 0


def _result_payload(result: object) -> dict[str, object]:
    return {
        "strategy": result.strategy_name,
        "metrics": asdict(result.metrics),
        "trades": [
            {
                "symbol": trade.symbol,
                "date": trade.date,
                "action": trade.action.value,
                "quantity": trade.quantity,
                "price": trade.price,
                "cash_delta": round(trade.cash_delta, 10),
            }
            for trade in result.trades
        ],
        "equity_curve": [asdict(snapshot) for snapshot in result.equity_curve],
    }


if __name__ == "__main__":
    raise SystemExit(main())
