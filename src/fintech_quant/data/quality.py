from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


REQUIRED_DAILY_COLUMNS = ("代码", "名称", "date", "open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class DailyDataQualityReport:
    rows: int
    symbols: int
    duplicate_symbol_dates: int
    missing_required_values: int
    ohlc_violations: int
    negative_volume_rows: int

    @property
    def passes_core_checks(self) -> bool:
        return (
            self.rows > 0
            and self.symbols > 0
            and self.duplicate_symbol_dates == 0
            and self.missing_required_values == 0
            and self.ohlc_violations == 0
            and self.negative_volume_rows == 0
        )


def audit_daily_records(records: Sequence[Mapping[str, Any]]) -> DailyDataQualityReport:
    symbol_dates: set[tuple[str, str]] = set()
    duplicate_symbol_dates = 0
    missing_required_values = 0
    ohlc_violations = 0
    negative_volume_rows = 0
    symbols: set[str] = set()

    for record in records:
        symbol = str(record.get("代码", "")).strip()
        record_date = str(record.get("date", "")).strip()
        if symbol:
            symbols.add(symbol)

        key = (symbol, record_date)
        if key in symbol_dates:
            duplicate_symbol_dates += 1
        else:
            symbol_dates.add(key)

        if any(_is_missing(record.get(column)) for column in REQUIRED_DAILY_COLUMNS):
            missing_required_values += 1

        open_price = _number(record.get("open"))
        high = _number(record.get("high"))
        low = _number(record.get("low"))
        close = _number(record.get("close"))
        if high < max(open_price, low, close) or low > min(open_price, high, close):
            ohlc_violations += 1

        volume = _number(record.get("volume"))
        if volume < 0:
            negative_volume_rows += 1

    return DailyDataQualityReport(
        rows=len(records),
        symbols=len(symbols),
        duplicate_symbol_dates=duplicate_symbol_dates,
        missing_required_values=missing_required_values,
        ohlc_violations=ohlc_violations,
        negative_volume_rows=negative_volume_rows,
    )


def _is_missing(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
