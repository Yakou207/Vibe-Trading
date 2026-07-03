from __future__ import annotations

import csv
import importlib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from fintech_quant.data.errors import MissingProviderDependency, ProviderFetchError
from fintech_quant.data.symbols import normalize_a_share_symbol


REALTIME_QUOTE_FIELDS = (
    "symbol",
    "name",
    "price",
    "change_pct",
    "change_amount",
    "volume",
    "amount",
    "turnover_rate",
    "pe_dynamic",
    "pb",
    "source",
)


class AkShareRealtimeQuoteProvider:
    name = "akshare"

    def __init__(self, fetcher: Callable[[], object] | None = None) -> None:
        self._fetcher = fetcher

    def quotes(self, symbols: Sequence[str] | None = None) -> list[dict[str, object]]:
        symbol_set = {normalize_a_share_symbol(symbol) for symbol in symbols} if symbols else None
        try:
            rows = [normalize_realtime_quote(row, self.name) for row in self._fetch_rows()]
        except MissingProviderDependency:
            raise
        except Exception as exc:
            raise ProviderFetchError("akshare realtime quote fetch failed") from exc
        if symbol_set is None:
            return rows
        return [row for row in rows if str(row["symbol"]) in symbol_set]

    def _fetch_rows(self) -> list[Mapping[str, object]]:
        if self._fetcher is not None:
            return list(self._fetcher())
        try:
            ak = importlib.import_module("akshare")
        except ImportError as exc:
            raise MissingProviderDependency("akshare is required for AkShareRealtimeQuoteProvider") from exc
        return list(ak.stock_zh_a_spot_em().to_dict(orient="records"))


def normalize_realtime_quote(row: Mapping[str, object], source: str) -> dict[str, object]:
    normalized = {
        "symbol": normalize_a_share_symbol(str(_require_value(row, "symbol", ("symbol", "代码")))),
        "name": str(_optional_value(row, ("name", "名称")) or ""),
        "price": _require_float(row, "price", ("price", "最新价")),
        "change_pct": _optional_percent(row, ("change_pct", "涨跌幅")),
        "change_amount": _optional_float(row, ("change_amount", "涨跌额")),
        "volume": _optional_float(row, ("volume", "成交量")),
        "amount": _optional_float(row, ("amount", "成交额")),
        "turnover_rate": _optional_percent(row, ("turnover_rate", "换手率")),
        "pe_dynamic": _optional_float(row, ("pe_dynamic", "市盈率-动态")),
        "pb": _optional_float(row, ("pb", "市净率")),
        "source": source,
    }
    return {key: value for key, value in normalized.items() if value is not None}


def write_realtime_quotes_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REALTIME_QUOTE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in REALTIME_QUOTE_FIELDS})


def _require_value(row: Mapping[str, object], field_name: str, keys: tuple[str, ...]) -> object:
    value = _optional_value(row, keys)
    if value is None:
        raise ValueError(f"Realtime quote is missing required field: {field_name}")
    return value


def _optional_value(row: Mapping[str, object], keys: tuple[str, ...]) -> object | None:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _require_float(row: Mapping[str, object], field_name: str, keys: tuple[str, ...]) -> float:
    value = _require_value(row, field_name, keys)
    try:
        return _float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Realtime quote field {field_name} must be numeric: {value!r}") from exc


def _optional_float(row: Mapping[str, object], keys: tuple[str, ...]) -> float | None:
    value = _optional_value(row, keys)
    if value is None:
        return None
    return _float(value)


def _optional_percent(row: Mapping[str, object], keys: tuple[str, ...]) -> float | None:
    value = _optional_float(row, keys)
    if value is None:
        return None
    return round(value / 100.0, 6)


def _float(value: object) -> float:
    return float(str(value).replace(",", "").strip())
