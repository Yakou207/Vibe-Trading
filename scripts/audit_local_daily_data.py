from __future__ import annotations

import argparse
import json
from pathlib import Path

from fintech_quant.data.quality import audit_daily_records


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit local daily market data CSV files.")
    parser.add_argument("--daily-csv", default="data/processed/akshare_research_daily.csv")
    parser.add_argument("--output", default="outputs/data_quality_report.json")
    args = parser.parse_args()

    import pandas as pd

    daily_path = Path(args.daily_csv)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    daily = pd.read_csv(daily_path)
    report = audit_daily_records(daily.to_dict("records"))
    date_min = str(daily["date"].min())
    date_max = str(daily["date"].max())
    rows_by_symbol = daily.groupby("代码").size().sort_values(ascending=False)
    max_date_by_symbol = daily.groupby("代码")["date"].max()
    stale_symbols = max_date_by_symbol[max_date_by_symbol < date_max].to_dict()

    payload = {
        "source": str(daily_path),
        "rows": report.rows,
        "symbols": report.symbols,
        "date_min": date_min,
        "date_max": date_max,
        "duplicate_symbol_dates": report.duplicate_symbol_dates,
        "missing_required_values": report.missing_required_values,
        "ohlc_violations": report.ohlc_violations,
        "negative_volume_rows": report.negative_volume_rows,
        "passes_core_checks": report.passes_core_checks,
        "rows_by_symbol_min": int(rows_by_symbol.min()),
        "rows_by_symbol_max": int(rows_by_symbol.max()),
        "stale_symbol_count": len(stale_symbols),
        "stale_symbols": stale_symbols,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if report.passes_core_checks else 1


if __name__ == "__main__":
    raise SystemExit(main())
