from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping

from fintech_quant.data.research_dataset import DEFAULT_FEATURE_FIELDS, load_universe_csv
from fintech_quant.data.symbols import normalize_a_share_symbol
from fintech_quant.information import InformationCategory, InformationRecord


_BOOLEAN_FIELDS = {
    "close_above_ma20",
    "close_above_ma60",
    "close_above_ma250",
    "macd_positive",
    "margin_financing_positive",
    "st_warning",
    "index_below_annual_ma",
    "is_suspended",
    "suspended",
    "limit_up",
    "is_limit_up",
    "limit_down",
    "is_limit_down",
}
_INT_FIELDS = {
    "main_outflow_days",
    "broad_market_drop_gt_3pct_count",
}
_FLOAT_FIELDS = {
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "return_1d",
    "ma20",
    "ma60",
    "ma250",
    "rsi14",
    "macd_line",
    "macd_signal",
    "macd_hist",
    "volatility20",
    "pe",
    "pb",
    "roe",
    "growth",
    "goodwill_ratio",
    "pledge_ratio",
    "main_net_inflow",
}


@dataclass(frozen=True)
class FeatureRow:
    symbol: str
    trade_date: date
    values: dict[str, object]


@dataclass(frozen=True)
class SupplementalRow:
    symbol: str
    trade_date: date | None
    values: dict[str, object]


@dataclass(frozen=True)
class MarketStateRow:
    trade_date: date
    values: dict[str, object]


@dataclass(frozen=True)
class ResearchDataset:
    features: list[FeatureRow]
    fundamentals: dict[tuple[str, date | None], SupplementalRow]
    capital_flow: dict[tuple[str, date], SupplementalRow]
    market_state: dict[date, MarketStateRow]
    information_records: list[InformationRecord]
    universe_symbols: tuple[str, ...]


def load_research_dataset(
    features_path: Path,
    universe_path: Path,
    *,
    fundamentals_path: Path | None = None,
    capital_flow_path: Path | None = None,
    market_state_path: Path | None = None,
    information_path: Path | None = None,
) -> ResearchDataset:
    universe_symbols = tuple(member.symbol for member in load_universe_csv(universe_path))
    universe_set = set(universe_symbols)
    return ResearchDataset(
        features=_load_features(features_path, universe_set),
        fundamentals=_load_supplemental(fundamentals_path, universe_set, allow_missing_trade_date=True),
        capital_flow=_load_supplemental(capital_flow_path, universe_set, allow_missing_trade_date=False),
        market_state=_load_market_state(market_state_path),
        information_records=_load_information(information_path, universe_set),
        universe_symbols=universe_symbols,
    )


def _load_features(path: Path, universe_symbols: set[str]) -> list[FeatureRow]:
    rows = _read_csv(path)
    _require_columns(path, rows.fieldnames, DEFAULT_FEATURE_FIELDS)
    features: list[FeatureRow] = []
    seen: set[tuple[str, date]] = set()
    for row in rows.records:
        symbol = normalize_a_share_symbol(str(row["symbol"]))
        if symbol not in universe_symbols:
            continue
        trade_date = _parse_date(row["trade_date"], path, "trade_date")
        key = (symbol, trade_date)
        if key in seen:
            raise ValueError(f"Duplicate feature row for {symbol} on {trade_date.isoformat()}")
        seen.add(key)
        values = _coerce_row(row, path)
        values["symbol"] = symbol
        values["trade_date"] = trade_date
        features.append(FeatureRow(symbol=symbol, trade_date=trade_date, values=values))
    return sorted(features, key=lambda item: (item.trade_date, item.symbol))


def _load_supplemental(
    path: Path | None,
    universe_symbols: set[str],
    *,
    allow_missing_trade_date: bool,
) -> dict[tuple[str, date | None], SupplementalRow]:
    if path is None:
        return {}
    rows = _read_csv(path)
    _require_columns(path, rows.fieldnames, ("symbol",))
    result: dict[tuple[str, date | None], SupplementalRow] = {}
    for row in rows.records:
        symbol = normalize_a_share_symbol(str(row["symbol"]))
        if symbol not in universe_symbols:
            continue
        trade_date = _optional_trade_date(row, path, allow_missing_trade_date)
        values = _coerce_row(row, path)
        values["symbol"] = symbol
        if trade_date is not None:
            values["trade_date"] = trade_date
        result[(symbol, trade_date)] = SupplementalRow(symbol=symbol, trade_date=trade_date, values=values)
    return result


def _load_market_state(path: Path | None) -> dict[date, MarketStateRow]:
    if path is None:
        return {}
    rows = _read_csv(path)
    _require_columns(path, rows.fieldnames, ("trade_date",))
    result: dict[date, MarketStateRow] = {}
    for row in rows.records:
        trade_date = _parse_date(row["trade_date"], path, "trade_date")
        values = _coerce_row(row, path)
        values["trade_date"] = trade_date
        result[trade_date] = MarketStateRow(trade_date=trade_date, values=values)
    return result


def _load_information(path: Path | None, universe_symbols: set[str]) -> list[InformationRecord]:
    if path is None:
        return []
    if not path.exists():
        raise FileNotFoundError(path)
    records: list[InformationRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = _information_from_json(json.loads(line))
            if record.normalized_symbol in universe_symbols:
                records.append(record)
    return sorted(records, key=lambda item: (item.published_at, item.normalized_symbol or "", item.title))


@dataclass(frozen=True)
class _CsvRows:
    fieldnames: tuple[str, ...]
    records: list[dict[str, str]]


def _read_csv(path: Path) -> _CsvRows:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return _CsvRows(tuple(reader.fieldnames or ()), [dict(row) for row in reader])


def _require_columns(path: Path, fieldnames: tuple[str, ...], required: tuple[str, ...]) -> None:
    missing = [field for field in required if field not in fieldnames]
    if missing:
        raise ValueError(f"{path} is missing required columns: {', '.join(missing)}")


def _optional_trade_date(row: Mapping[str, str], path: Path, allow_missing: bool) -> date | None:
    raw_value = row.get("trade_date", "")
    if raw_value in ("", None):
        if allow_missing:
            return None
        raise ValueError(f"{path} is missing trade_date")
    return _parse_date(raw_value, path, "trade_date")


def _coerce_row(row: Mapping[str, str], path: Path) -> dict[str, object]:
    return {key: _coerce_value(key, value, path) for key, value in row.items()}


def _coerce_value(key: str, value: object, path: Path) -> object:
    if value in (None, ""):
        return None
    if key in _BOOLEAN_FIELDS:
        return _parse_bool(str(value), path, key)
    if key in _INT_FIELDS:
        try:
            return int(float(str(value)))
        except ValueError as exc:
            raise ValueError(f"{path} has invalid integer field {key}: {value!r}") from exc
    if key in _FLOAT_FIELDS:
        try:
            return float(str(value))
        except ValueError as exc:
            raise ValueError(f"{path} has invalid numeric field {key}: {value!r}") from exc
    return str(value)


def _parse_bool(value: str, path: Path, field: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError(f"{path} has invalid boolean field {field}: {value!r}")


def _parse_date(value: object, path: Path, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{path} has invalid date field {field}: {value!r}") from exc


def _information_from_json(data: dict[str, object]) -> InformationRecord:
    return InformationRecord(
        symbol=data.get("symbol") if isinstance(data.get("symbol"), str) else None,
        sector=data.get("sector") if isinstance(data.get("sector"), str) else None,
        published_at=date.fromisoformat(str(data["published_at"])),
        source=str(data["source"]),
        category=InformationCategory(str(data["category"])),
        title=str(data["title"]),
        url=str(data.get("url", "")),
        summary=str(data.get("summary", "")),
        risk_tags=tuple(str(tag) for tag in data.get("risk_tags", ())),
    )
