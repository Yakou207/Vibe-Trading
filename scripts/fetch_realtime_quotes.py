from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.data import (  # noqa: E402
    AkShareRealtimeQuoteProvider,
    load_universe_csv,
    normalize_a_share_symbol,
    normalize_realtime_quote,
    write_realtime_quotes_csv,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch realtime A-share quotes.")
    parser.add_argument("--source", choices=("akshare", "json"), default="akshare")
    parser.add_argument("--input", default=None, help="JSON quote fixture when --source json.")
    parser.add_argument("--symbols", default=None, help="Comma-separated A-share symbols to keep.")
    parser.add_argument("--universe", default=None, help="CSV universe with a symbol column.")
    parser.add_argument("--output", default="data/raw/realtime_quotes/a_share_realtime_quotes.csv")
    args = parser.parse_args()

    symbols = _symbols_from_args(args.symbols, args.universe)
    if args.source == "json":
        if not args.input:
            raise SystemExit("--input is required when --source json")
        rows = _load_json_quotes(Path(args.input), symbols)
    else:
        rows = AkShareRealtimeQuoteProvider().quotes(symbols)

    write_realtime_quotes_csv(Path(args.output), rows)
    print(f"quote_rows={len(rows)}")
    print(f"output={args.output}")
    return 0


def _symbols_from_args(symbols: str | None, universe_path: str | None) -> list[str] | None:
    selected: list[str] = []
    if symbols:
        selected.extend(normalize_a_share_symbol(symbol.strip()) for symbol in symbols.split(",") if symbol.strip())
    if universe_path:
        selected.extend(member.symbol for member in load_universe_csv(Path(universe_path)))
    return selected or None


def _load_json_quotes(path: Path, symbols: list[str] | None) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("JSON input must be a list of quote objects")
    rows = [normalize_realtime_quote(dict(item), "json") for item in payload]
    if symbols is None:
        return rows
    symbol_set = set(_symbols_from_args(",".join(symbols), None) or [])
    return [row for row in rows if str(row["symbol"]) in symbol_set]


if __name__ == "__main__":
    raise SystemExit(main())
