from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.data import (  # noqa: E402
    AkShareProvider,
    ProviderRegistry,
    TushareProvider,
    collect_universe_history,
    load_universe_csv,
    normalize_daily_bar,
    write_daily_bars_csv,
    write_feature_rows_csv,
)
from fintech_quant.features import enrich_daily_bars  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh local A-share research data and features.")
    parser.add_argument("--source", choices=("json", "auto", "akshare", "tushare"), default="json")
    parser.add_argument("--input", default=None, help="JSON daily-bar fixture path when --source json.")
    parser.add_argument("--universe", required=True, help="CSV with at least a symbol column.")
    parser.add_argument("--start", default=None, help="Provider mode start date, YYYY-MM-DD.")
    parser.add_argument("--end", default=None, help="Provider mode end date, YYYY-MM-DD.")
    parser.add_argument("--daily-output", default="data/processed/akshare_research_daily.csv")
    parser.add_argument("--feature-output", default="data/processed/akshare_research_features.csv")
    args = parser.parse_args()

    universe = load_universe_csv(Path(args.universe))
    if args.source == "json":
        if not args.input:
            raise SystemExit("--input is required when --source json")
        daily_rows = _load_json_rows(Path(args.input))
    else:
        if not args.start or not args.end:
            raise SystemExit("--start and --end are required for provider sources")
        registry = _build_registry()
        provider = registry.get(args.source)
        daily_rows = collect_universe_history(
            provider,
            universe,
            date.fromisoformat(args.start),
            date.fromisoformat(args.end),
        )

    universe_symbols = {member.symbol for member in universe}
    selected_rows = sorted(
        [row for row in daily_rows if str(row["symbol"]) in universe_symbols],
        key=lambda row: (str(row["symbol"]), str(row["trade_date"])),
    )
    feature_rows = enrich_daily_bars(selected_rows)
    write_daily_bars_csv(Path(args.daily_output), selected_rows)
    write_feature_rows_csv(Path(args.feature_output), feature_rows)
    print(f"daily_rows={len(selected_rows)}")
    print(f"feature_rows={len(feature_rows)}")
    return 0


def _load_json_rows(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("JSON input must be a list of daily-bar objects")
    return [
        normalize_daily_bar(str(item["symbol"]), dict(item), str(item.get("source", "json")))
        for item in payload
    ]


def _build_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(AkShareProvider())
    registry.register(TushareProvider())
    return registry


if __name__ == "__main__":
    raise SystemExit(main())
