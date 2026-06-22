from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
import re
from typing import Any, Mapping

from fintech_quant.data.symbols import normalize_a_share_symbol


class MarketDataProvider(ABC):
    name: str

    @abstractmethod
    def history(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        """Return daily bars or records for a symbol."""


def normalize_daily_bar(symbol: str, row: Mapping[str, object], source: str) -> dict[str, object]:
    trade_date = _first_present(row, ("trade_date", "date", "日期"))
    if trade_date is None:
        raise ValueError("Daily bar is missing trade_date/date/日期")
    return {
        "symbol": normalize_a_share_symbol(symbol),
        "trade_date": _normalize_trade_date(trade_date),
        "open": _float_value(_first_present(row, ("open", "开盘"))),
        "high": _float_value(_first_present(row, ("high", "最高"))),
        "low": _float_value(_first_present(row, ("low", "最低"))),
        "close": _float_value(_first_present(row, ("close", "收盘"))),
        "volume": _float_value(_first_present(row, ("volume", "vol", "成交量"))),
        "amount": _float_value(_first_present(row, ("amount", "成交额"))),
        "source": source,
    }


def _first_present(row: Mapping[str, object], keys: tuple[str, ...]) -> object | None:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _float_value(value: object | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _normalize_trade_date(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    raw_value = str(value).strip()
    if re.fullmatch(r"\d{8}", raw_value):
        return datetime.strptime(raw_value, "%Y%m%d").date().isoformat()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_value):
        return date.fromisoformat(raw_value).isoformat()
    try:
        return datetime.fromisoformat(raw_value).date().isoformat()
    except ValueError as exc:
        raise ValueError(f"Unsupported trade_date value: {value!r}") from exc
