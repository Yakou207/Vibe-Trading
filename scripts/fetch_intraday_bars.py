from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.data import normalize_a_share_symbol  # noqa: E402
from fintech_quant.intraday.minute_data import (  # noqa: E402
    fetch_sina_minute_bars,
    write_minute_bars_csv,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch 5-minute bars (Sina) for the rotation universe.")
    parser.add_argument("--symbols", required=True, help="Comma-separated, e.g. 600000.SH,000001.SZ")
    parser.add_argument("--output-dir", default="data/raw/intraday_5min")
    parser.add_argument("--period", default="5")
    parser.add_argument("--pause-seconds", type=float, default=1.0)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    for raw_symbol in args.symbols.split(","):
        symbol = normalize_a_share_symbol(raw_symbol.strip())
        bars = fetch_sina_minute_bars(symbol, period=args.period)
        path = output_dir / f"{symbol}.csv"
        write_minute_bars_csv(path, bars)
        first = bars[0]["datetime"] if bars else "-"
        last = bars[-1]["datetime"] if bars else "-"
        print(f"{symbol}: rows={len(bars)} range={first} .. {last} -> {path}")
        time.sleep(args.pause_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
