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
_MAX_CONTINUOUS_OUTFLOW_GAP_DAYS = 3


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
    universe = load_universe_csv(universe_path)
    universe_symbols = tuple(member.symbol for member in universe)
    universe_set = set(universe_symbols)
    universe_sectors = {member.sector for member in universe if member.sector}
    sector_by_symbol = {member.symbol: member.sector for member in universe}
    information_records = _load_information(information_path, universe_set, universe_sectors)
    fundamentals = _load_supplemental(fundamentals_path, universe_set, allow_missing_trade_date=True)
    _merge_information_fundamentals(fundamentals, information_records, universe_set)
    capital_flow = _load_supplemental(capital_flow_path, universe_set, allow_missing_trade_date=False)
    _merge_information_capital_flow(capital_flow, information_records, universe_set)
    return ResearchDataset(
        features=_load_features(features_path, universe_set, sector_by_symbol),
        fundamentals=fundamentals,
        capital_flow=capital_flow,
        market_state=_load_market_state(market_state_path),
        information_records=information_records,
        universe_symbols=universe_symbols,
    )


def _load_features(
    path: Path,
    universe_symbols: set[str],
    sector_by_symbol: Mapping[str, str | None],
) -> list[FeatureRow]:
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
        values["sector"] = sector_by_symbol.get(symbol)
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


def _load_information(
    path: Path | None,
    universe_symbols: set[str],
    universe_sectors: set[str],
) -> list[InformationRecord]:
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
            if record.normalized_symbol in universe_symbols or (record.symbol is None and record.sector in universe_sectors):
                records.append(record)
    return sorted(records, key=lambda item: (item.published_at, item.normalized_symbol or "", item.title))


def _merge_information_fundamentals(
    fundamentals: dict[tuple[str, date | None], SupplementalRow],
    records: list[InformationRecord],
    universe_symbols: set[str],
) -> None:
    for record in records:
        if (
            record.source != "akshare_fundamental"
            or record.category is not InformationCategory.STOCK_DATA
            or "fundamental" not in record.risk_tags
        ):
            continue
        symbol = record.normalized_symbol
        if symbol is None or symbol not in universe_symbols:
            continue
        if (symbol, None) in fundamentals:
            continue
        values = _parse_fundamental_summary(record.summary)
        if not values:
            continue
        values["symbol"] = symbol
        values["trade_date"] = record.published_at
        key = (symbol, record.published_at)
        fundamentals.setdefault(key, SupplementalRow(symbol=symbol, trade_date=record.published_at, values=values))


def _parse_fundamental_summary(summary: str) -> dict[str, object]:
    values: dict[str, object] = {}
    for part in summary.split(";"):
        if "=" not in part:
            continue
        key, raw_value = (item.strip() for item in part.split("=", 1))
        if key not in {"pe", "pb", "roe", "growth"}:
            continue
        try:
            values[key] = float(raw_value)
        except ValueError:
            continue
    return values


def _merge_information_capital_flow(
    capital_flow: dict[tuple[str, date], SupplementalRow],
    records: list[InformationRecord],
    universe_symbols: set[str],
) -> None:
    explicit_keys = set(capital_flow)
    fund_flow_records = [
        record
        for record in records
        if record.source == "akshare_fund_flow"
        and record.category is InformationCategory.STOCK_DATA
        and "capital_flow" in record.risk_tags
        and record.normalized_symbol in universe_symbols
    ]
    derived_fund_flow_records = [
        record
        for record in fund_flow_records
        if record.normalized_symbol is not None and (record.normalized_symbol, record.published_at) not in explicit_keys
    ]
    outflow_days_by_key = _main_outflow_days_by_key(derived_fund_flow_records, capital_flow)
    for record in fund_flow_records:
        symbol = record.normalized_symbol
        if symbol is None:
            continue
        key = (symbol, record.published_at)
        if key in explicit_keys:
            continue
        summary_values = _parse_summary_numbers(record.summary, {"main_net_inflow"})
        if "main_net_inflow" not in summary_values:
            continue
        values = _ensure_capital_flow_values(capital_flow, symbol, record.published_at)
        values.update(summary_values)
        values["main_outflow_days"] = outflow_days_by_key.get(key, 0)

    for record in records:
        if (
            record.source != "akshare_margin"
            or record.category is not InformationCategory.STOCK_DATA
            or "margin_financing" not in record.risk_tags
        ):
            continue
        symbol = record.normalized_symbol
        if symbol is None or symbol not in universe_symbols:
            continue
        key = (symbol, record.published_at)
        if key in explicit_keys:
            continue
        summary_values = _parse_summary_numbers(record.summary, {"margin_financing_positive"})
        margin_financing_positive = summary_values.get("margin_financing_positive")
        if margin_financing_positive is None:
            continue
        values = _ensure_capital_flow_values(capital_flow, symbol, record.published_at)
        values["margin_financing_positive"] = bool(margin_financing_positive)


def _ensure_capital_flow_values(
    capital_flow: dict[tuple[str, date], SupplementalRow],
    symbol: str,
    trade_date: date,
) -> dict[str, object]:
    key = (symbol, trade_date)
    row = capital_flow.get(key)
    if row is None:
        values: dict[str, object] = {"symbol": symbol, "trade_date": trade_date}
        capital_flow[key] = SupplementalRow(symbol=symbol, trade_date=trade_date, values=values)
        return values
    return row.values


def _main_outflow_days_by_key(
    records: list[InformationRecord],
    explicit_rows: dict[tuple[str, date], SupplementalRow],
) -> dict[tuple[str, date], int]:
    grouped: dict[str, list[tuple[date, InformationRecord | SupplementalRow]]] = {}
    for record in records:
        if record.normalized_symbol is not None:
            grouped.setdefault(record.normalized_symbol, []).append((record.published_at, record))
    for (symbol, trade_date), row in explicit_rows.items():
        grouped.setdefault(symbol, []).append((trade_date, row))

    result: dict[tuple[str, date], int] = {}
    for symbol, symbol_events in grouped.items():
        streak = 0
        previous_date: date | None = None
        for event_date, event in sorted(symbol_events, key=lambda item: item[0]):
            if (
                previous_date is not None
                and (event_date - previous_date).days > _MAX_CONTINUOUS_OUTFLOW_GAP_DAYS
            ):
                streak = 0
            if isinstance(event, SupplementalRow):
                streak = _explicit_outflow_streak(event, streak)
            else:
                values = _parse_summary_numbers(event.summary, {"main_net_inflow"})
                main_net_inflow = values.get("main_net_inflow")
                streak = streak + 1 if main_net_inflow is not None and float(main_net_inflow) < 0 else 0
                result[(symbol, event_date)] = streak
            previous_date = event_date
    return result


def _explicit_outflow_streak(row: SupplementalRow, previous_streak: int) -> int:
    raw_streak = row.values.get("main_outflow_days")
    if isinstance(raw_streak, int):
        return raw_streak

    raw_inflow = row.values.get("main_net_inflow")
    if isinstance(raw_inflow, (float, int)):
        return previous_streak + 1 if float(raw_inflow) < 0 else 0
    return 0


def _parse_summary_numbers(summary: str, allowed_keys: set[str]) -> dict[str, object]:
    values: dict[str, object] = {}
    for part in summary.split(";"):
        if "=" not in part:
            continue
        key, raw_value = (item.strip() for item in part.split("=", 1))
        if key not in allowed_keys:
            continue
        try:
            values[key] = float(raw_value)
        except ValueError:
            continue
    return values


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
