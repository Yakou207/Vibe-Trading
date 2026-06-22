from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from fintech_quant.data.symbols import normalize_a_share_symbol


DAILY_BAR_FIELDS = ("symbol", "trade_date", "open", "high", "low", "close", "volume", "amount", "source")
DEFAULT_FEATURE_FIELDS = (
    *DAILY_BAR_FIELDS,
    "return_1d",
    "ma20",
    "ma60",
    "ma250",
    "close_above_ma20",
    "close_above_ma60",
    "close_above_ma250",
    "rsi14",
    "macd_line",
    "macd_signal",
    "macd_hist",
    "macd_positive",
    "volatility20",
)


@dataclass(frozen=True)
class UniverseMember:
    symbol: str
    name: str | None = None
    sector: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", normalize_a_share_symbol(self.symbol))


class HistoryProvider(Protocol):
    def history(self, symbol: str, start: date, end: date) -> list[dict[str, object]]:
        """Return normalized daily bars for symbol between start and end."""


def load_universe_csv(path: Path) -> list[UniverseMember]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if "symbol" not in (reader.fieldnames or ()):
            raise ValueError("Universe CSV must contain a symbol column")
        return [
            UniverseMember(
                symbol=str(row["symbol"]),
                name=_optional_text(row.get("name")),
                sector=_optional_text(row.get("sector")),
            )
            for row in reader
            if row.get("symbol")
        ]


def collect_universe_history(
    provider: HistoryProvider,
    universe: Sequence[UniverseMember],
    start: date,
    end: date,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for member in universe:
        for row in provider.history(member.symbol, start, end):
            normalized_row = dict(row)
            normalized_row["symbol"] = member.symbol
            rows.append(normalized_row)
    return sorted(rows, key=lambda row: (str(row["symbol"]), str(row["trade_date"])))


def write_daily_bars_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    _write_csv(path, rows, DAILY_BAR_FIELDS)


def write_feature_rows_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    _write_csv(path, rows, DEFAULT_FEATURE_FIELDS)


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(rows, key=lambda item: (str(item["symbol"]), str(item["trade_date"]))):
            writer.writerow({field: _csv_value(row.get(field)) for field in fieldnames})


def _optional_text(value: object | None) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _csv_value(value: object | None) -> object:
    return "" if value is None else value
