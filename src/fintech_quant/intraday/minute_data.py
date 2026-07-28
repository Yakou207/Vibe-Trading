"""Fetch and store 5-minute bars (Sina via AkShare) for the rotation universe.

Sina keeps roughly two months of 5-minute history per symbol; the 1-minute feed
is only about eight days deep, so 5-minute is the deepest free option. Prices
are unadjusted — days with corporate actions are dropped at load time by
comparing to the daily close series.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping

from fintech_quant.data.symbols import normalize_a_share_symbol

MINUTE_BAR_FIELDS = ("datetime", "open", "high", "low", "close", "volume")


def fetch_sina_minute_bars(symbol: str, *, period: str = "5") -> list[dict[str, object]]:
    import akshare as ak

    normalized = normalize_a_share_symbol(symbol)
    code, exchange = normalized.split(".")
    frame = ak.stock_zh_a_minute(symbol=f"{exchange.lower()}{code}", period=period, adjust="")
    bars: list[dict[str, object]] = []
    for row in frame.to_dict(orient="records"):
        bars.append(
            {
                "datetime": str(row["day"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }
        )
    return bars


def write_minute_bars_csv(path: Path, bars: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MINUTE_BAR_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(bars)


def load_minute_bars_csv(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [
        {
            "datetime": row["datetime"],
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        }
        for row in rows
    ]


def bars_by_day(bars: Iterable[Mapping[str, object]]) -> dict[str, list[dict[str, object]]]:
    """Group minute bars by calendar day (bar datetime prefix ``YYYY-MM-DD``)."""
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for bar in bars:
        grouped[str(bar["datetime"])[:10]].append(dict(bar))
    return {day: sorted(rows, key=lambda b: str(b["datetime"])) for day, rows in sorted(grouped.items())}


def drop_corporate_action_days(
    days: Mapping[str, list[dict[str, object]]],
) -> dict[str, list[dict[str, object]]]:
    """Drop a day when its open gaps >8% from the prior day's close.

    Unadjusted prices jump on ex-dividend/ex-rights days, which would poison the
    intraday VWAP; A-share price limits make a legitimate >8% open gap rare
    enough that dropping the day costs little.
    """
    kept: dict[str, list[dict[str, object]]] = {}
    prior_close: float | None = None
    for day, rows in days.items():
        day_open = float(rows[0]["open"])
        if prior_close is None or abs(day_open / prior_close - 1.0) <= 0.08:
            kept[day] = rows
        prior_close = float(rows[-1]["close"])
    return kept
