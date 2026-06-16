from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence


STAR_MARKET_PREFIXES = ("688", "689")


@dataclass(frozen=True)
class StockCandidate:
    symbol: str
    name: str
    turnover: float


@dataclass(frozen=True)
class AkShareDateRange:
    start: str
    end: str


@dataclass(frozen=True)
class DataSizeEstimate:
    rows: int
    csv_megabytes: float
    runtime_megabytes: float


def one_year_akshare_date_range(today: date | None = None) -> AkShareDateRange:
    end = today or date.today()
    start = end - timedelta(days=365)
    return AkShareDateRange(
        start=start.strftime("%Y%m%d"),
        end=end.strftime("%Y%m%d"),
    )


def akshare_date_to_iso(value: str) -> str:
    if len(value) != 8:
        raise ValueError(f"Expected YYYYMMDD date, got {value!r}.")
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def date_value_to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    normalized = str(value).strip()
    if len(normalized) == 8 and normalized.isdigit():
        return akshare_date_to_iso(normalized)
    return normalized[:10]


def estimate_daily_collection_size(
    symbol_count: int,
    trading_days: int = 250,
    csv_bytes_per_row: int = 220,
    runtime_bytes_per_row: int = 1_200,
) -> DataSizeEstimate:
    rows = symbol_count * trading_days
    bytes_per_megabyte = 1024 * 1024
    return DataSizeEstimate(
        rows=rows,
        csv_megabytes=round(rows * csv_bytes_per_row / bytes_per_megabyte, 2),
        runtime_megabytes=round(rows * runtime_bytes_per_row / bytes_per_megabyte, 2),
    )


def select_star_market_universe(
    records: Sequence[Mapping[str, Any]],
    limit: int = 30,
) -> list[StockCandidate]:
    candidates = [
        StockCandidate(
            symbol=str(record.get("代码", "")).strip(),
            name=str(record.get("名称", "")).strip(),
            turnover=_number(record.get("成交额", record.get("成交量", 0))),
        )
        for record in records
    ]
    star_candidates = [
        candidate
        for candidate in candidates
        if _is_star_market_symbol(candidate.symbol)
    ]
    return sorted(star_candidates, key=lambda item: item.turnover, reverse=True)[:limit]


def build_research_universe(
    records: Sequence[Mapping[str, Any]],
    star_limit: int = 30,
) -> list[StockCandidate]:
    return select_star_market_universe(records, limit=star_limit)


def _is_star_market_symbol(symbol: str) -> bool:
    normalized = symbol.removeprefix("sh").removeprefix("SH")
    return normalized.startswith(STAR_MARKET_PREFIXES)


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    normalized = str(value).replace(",", "").strip()
    if not normalized:
        return 0.0
    try:
        return float(normalized)
    except ValueError:
        return 0.0
