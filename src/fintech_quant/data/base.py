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
    trade_date = _require_value(row, "trade_date", ("trade_date", "date", "日期"))
    normalized = {
        "symbol": normalize_a_share_symbol(symbol),
        "trade_date": _normalize_trade_date(trade_date),
        "open": _require_float(row, "open", ("open", "开盘")),
        "high": _require_float(row, "high", ("high", "最高")),
        "low": _require_float(row, "low", ("low", "最低")),
        "close": _require_float(row, "close", ("close", "收盘")),
        "volume": _require_float(row, "volume", ("volume", "vol", "成交量")),
        "amount": _require_float(row, "amount", ("amount", "成交额")),
        "source": source,
    }
    limit_up = _optional_bool(row, ("limit_up", "is_limit_up", "涨停"))
    if limit_up is not None:
        normalized["limit_up"] = limit_up
    return normalized


def _first_present(row: Mapping[str, object], keys: tuple[str, ...]) -> object | None:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _require_value(row: Mapping[str, object], field_name: str, keys: tuple[str, ...]) -> object:
    value = _first_present(row, keys)
    if value is None:
        raise ValueError(f"Daily bar is missing required field: {field_name}")
    return value


def _require_float(row: Mapping[str, object], field_name: str, keys: tuple[str, ...]) -> float:
    value = _require_value(row, field_name, keys)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Daily bar field {field_name} must be numeric: {value!r}") from exc


def _optional_bool(row: Mapping[str, object], keys: tuple[str, ...]) -> bool | None:
    value = _first_present(row, keys)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError(f"Daily bar boolean field must be true/false-like: {value!r}")


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
