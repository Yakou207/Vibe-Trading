from __future__ import annotations

import argparse
import csv
import importlib
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.data.errors import MissingProviderDependency, ProviderFetchError


@dataclass(frozen=True)
class IndexBar:
    trade_date: date
    close: float


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch A-share index market state for risk monitoring.")
    parser.add_argument("--source", choices=("akshare", "csv"), default="akshare")
    parser.add_argument("--input", default=None, help="CSV input path when --source csv.")
    parser.add_argument("--index-symbol", default="sh000001")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", default="data/raw/market_state/sh000001_market_state.csv")
    parser.add_argument("--ma-window", type=int, default=250)
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    bars = _load_index_bars(args.source, args.index_symbol, start, end, args.input)
    rows = _build_market_state_rows(bars, args.index_symbol, start, end, args.ma_window)
    _write_market_state(Path(args.output), rows)
    print(f"stored_market_state_rows={len(rows)}")
    return 0


def _load_index_bars(
    source: str,
    index_symbol: str,
    start: date,
    end: date,
    input_path: str | None,
) -> list[IndexBar]:
    if source == "csv":
        if input_path is None:
            raise SystemExit("--input is required when --source csv")
        return _bars_from_csv(Path(input_path))
    return _bars_from_akshare(index_symbol, start, end)


def _bars_from_csv(path: Path) -> list[IndexBar]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return sorted((_bar_from_row(row) for row in reader), key=lambda bar: bar.trade_date)


def _bars_from_akshare(index_symbol: str, start: date, end: date) -> list[IndexBar]:
    try:
        ak = importlib.import_module("akshare")
    except ImportError as exc:
        raise MissingProviderDependency("akshare is required for fetch_market_state.py") from exc

    try:
        rows = ak.stock_zh_index_daily_em(
            symbol=index_symbol,
            start_date="",
            end_date=end.strftime("%Y%m%d"),
        ).to_dict(orient="records")
    except Exception as exc:
        rows = _fallback_index_rows(ak, index_symbol, start, end)
        if rows is None:
            raise ProviderFetchError(f"akshare index daily fetch failed for {index_symbol!r}") from exc
    return sorted((_bar_from_row(row) for row in rows), key=lambda bar: bar.trade_date)


def _fallback_index_rows(ak: object, index_symbol: str, start: date, end: date) -> list[dict[str, object]] | None:
    if _normalized_index_code(index_symbol) != "000300":
        return None
    try:
        return ak.stock_zh_index_hist_csindex(
            symbol="000300",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        ).to_dict(orient="records")
    except Exception:
        return None


def _normalized_index_code(index_symbol: str) -> str:
    return index_symbol.removeprefix("sh").removeprefix("sz")


def _bar_from_row(row: Mapping[str, object]) -> IndexBar:
    return IndexBar(
        trade_date=_parse_date(_first_value(row, "date", "日期", "trade_date")),
        close=_float(_first_value(row, "close", "收盘", "收盘价", "最新价", "index_close")),
    )


def _build_market_state_rows(
    bars: Iterable[IndexBar],
    index_symbol: str,
    start: date,
    end: date,
    ma_window: int,
) -> list[dict[str, object]]:
    if ma_window <= 0:
        raise ValueError("--ma-window must be positive")
    result: list[dict[str, object]] = []
    closes: list[float] = []
    for bar in sorted(bars, key=lambda item: item.trade_date):
        closes.append(bar.close)
        if len(closes) < ma_window:
            continue
        moving_average = sum(closes[-ma_window:]) / ma_window
        if start <= bar.trade_date <= end:
            result.append(
                {
                    "trade_date": bar.trade_date.isoformat(),
                    "index_symbol": index_symbol,
                    "index_close": round(bar.close, 6),
                    "index_ma250": round(moving_average, 6),
                    "index_below_annual_ma": "true" if bar.close < moving_average else "false",
                }
            )
    return result


def _write_market_state(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ("trade_date", "index_symbol", "index_close", "index_ma250", "index_below_annual_ma")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _first_value(row: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    raise ValueError(f"missing required field; expected one of {', '.join(keys)}")


def _parse_date(value: object) -> date:
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return date.fromisoformat(f"{text[:4]}-{text[4:6]}-{text[6:]}")
    return date.fromisoformat(text)


def _float(value: object) -> float:
    return float(str(value).replace(",", "").strip())


if __name__ == "__main__":
    raise SystemExit(main())
