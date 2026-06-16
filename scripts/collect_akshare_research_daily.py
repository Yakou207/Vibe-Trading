from __future__ import annotations

import argparse
from pathlib import Path

from fintech_quant.data.collection import (
    akshare_date_to_iso,
    build_research_universe,
    date_value_to_iso,
    estimate_daily_collection_size,
    one_year_akshare_date_range,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect one year of daily AkShare data for the research universe."
    )
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--adjust", default="qfq", choices=["", "qfq", "hfq"])
    parser.add_argument("--raw-dir", default="data/raw/akshare/daily")
    parser.add_argument("--processed-dir", default="data/processed")
    args = parser.parse_args()

    import akshare as ak
    import pandas as pd

    date_range = one_year_akshare_date_range()
    estimate = estimate_daily_collection_size(symbol_count=args.limit + 1)

    raw_dir = Path(args.raw_dir)
    processed_dir = Path(args.processed_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    spot_df = ak.stock_zh_kcb_spot()
    universe = build_research_universe(
        spot_df.to_dict("records"),
        star_limit=args.limit,
    )
    if len(universe) < args.limit + 1:
        raise RuntimeError(f"Only found {len(universe)} STAR Market symbols.")

    frames = []
    start_iso = akshare_date_to_iso(date_range.start)
    end_iso = akshare_date_to_iso(date_range.end)
    for candidate in universe:
        if candidate.symbol.startswith("sh688") or candidate.symbol.startswith("sh689"):
            history = ak.stock_zh_kcb_daily(symbol=candidate.symbol, adjust=args.adjust)
        else:
            history = ak.stock_zh_a_daily(
                symbol=candidate.symbol,
                start_date=date_range.start,
                end_date=date_range.end,
                adjust=args.adjust,
            )
        history["_date"] = history["date"].map(date_value_to_iso)
        history = history[(history["_date"] >= start_iso) & (history["_date"] <= end_iso)].copy()
        history = history.drop(columns=["_date"])
        history.insert(0, "代码", candidate.symbol)
        history.insert(1, "名称", candidate.name)
        history.to_csv(raw_dir / f"{candidate.symbol}.csv", index=False)
        frames.append(history)

    combined = pd.concat(frames, ignore_index=True)
    universe_df = pd.DataFrame(
        {
            "代码": [item.symbol for item in universe],
            "名称": [item.name for item in universe],
            "成交额": [item.turnover for item in universe],
        }
    )
    universe_df.to_csv(processed_dir / "akshare_research_universe.csv", index=False)
    combined.to_csv(processed_dir / "akshare_research_daily.csv", index=False)

    print(
        "Collected "
        f"{len(universe)} symbols from {date_range.start} to {date_range.end}; "
        f"estimated {estimate.rows} rows, ~{estimate.csv_megabytes} MB CSV."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
