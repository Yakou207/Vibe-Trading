"""Incrementally archive Sina 5-minute bars so a clean OOS window accumulates.

Sina only keeps ~2 months of 5-minute history, so run this every trading day
after the close: it merges the fresh fetch into the existing per-symbol CSV,
deduplicating on bar datetime. Data from 2026-07-29 onward is untouched by any
V3 experiment and forms the prospective evaluation window for the
pre-registered momentum hypothesis (see the V3 design doc).
"""

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
    load_minute_bars_csv,
    write_minute_bars_csv,
)

DEFAULT_UNIVERSE = (
    "600000.SH,600036.SH,601318.SH,600519.SH,601899.SH,"
    "000001.SZ,000333.SZ,000858.SZ,300750.SZ,002415.SZ"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge today's Sina 5-min bars into the archive.")
    parser.add_argument("--symbols", default=DEFAULT_UNIVERSE)
    parser.add_argument("--archive-dir", default="data/raw/intraday_5min")
    parser.add_argument("--pause-seconds", type=float, default=1.0)
    args = parser.parse_args()

    archive_dir = Path(args.archive_dir)
    for raw_symbol in args.symbols.split(","):
        symbol = normalize_a_share_symbol(raw_symbol.strip())
        path = archive_dir / f"{symbol}.csv"
        existing = load_minute_bars_csv(path) if path.exists() else []
        fresh = fetch_sina_minute_bars(symbol, period="5")
        merged = {str(bar["datetime"]): bar for bar in existing}
        added = 0
        for bar in fresh:
            if str(bar["datetime"]) not in merged:
                merged[str(bar["datetime"])] = bar
                added += 1
        ordered = [merged[key] for key in sorted(merged)]
        write_minute_bars_csv(path, ordered)
        print(f"{symbol}: +{added} bars, total {len(ordered)}, last {ordered[-1]['datetime'] if ordered else '-'}")
        time.sleep(args.pause_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
