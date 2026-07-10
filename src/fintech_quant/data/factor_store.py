from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping, Sequence

from fintech_quant.information import InformationRecord


FUNDAMENTAL_FIELDS = (
    "symbol",
    "report_period",
    "available_date",
    "source",
    "source_fetched_at",
    "pe",
    "pb",
    "roe",
    "growth",
    "goodwill_ratio",
)
CAPITAL_FLOW_FIELDS = (
    "symbol",
    "trade_date",
    "available_date",
    "source",
    "source_fetched_at",
    "main_net_inflow",
    "main_outflow_days",
    "margin_financing_positive",
)


@dataclass(frozen=True)
class FundamentalSnapshot:
    symbol: str
    report_period: date | None
    available_date: date
    source: str
    source_fetched_at: str
    values: dict[str, float | None]


@dataclass(frozen=True)
class CapitalFlowSnapshot:
    symbol: str
    trade_date: date
    available_date: date
    source: str
    source_fetched_at: str
    values: dict[str, float | int | bool | None]


def materialize_fundamentals(
    records: Sequence[InformationRecord],
    *,
    source_fetched_at: str,
) -> list[FundamentalSnapshot]:
    by_symbol: dict[str, list[InformationRecord]] = {}
    for record in records:
        if record.normalized_symbol is not None:
            by_symbol.setdefault(record.normalized_symbol, []).append(record)

    snapshots: list[FundamentalSnapshot] = []
    for symbol, symbol_records in sorted(by_symbol.items()):
        valuations = _valuation_events(symbol_records)
        financials = _financial_events(symbol_records)
        event_dates = sorted(set(valuations) | set(financials))
        current_valuation: dict[str, float | None] = {"pe": None, "pb": None}
        current_financial: dict[str, float | None] = {
            "roe": None,
            "growth": None,
            "goodwill_ratio": None,
        }
        current_report_period: date | None = None
        for available_date in event_dates:
            if available_date in valuations:
                current_valuation = valuations[available_date]
            if available_date in financials:
                current_report_period, current_financial = financials[available_date]
            snapshots.append(
                FundamentalSnapshot(
                    symbol=symbol,
                    report_period=current_report_period,
                    available_date=available_date,
                    source="akshare",
                    source_fetched_at=source_fetched_at,
                    values={**current_valuation, **current_financial},
                )
            )
    return snapshots


def materialize_capital_flow(
    records: Sequence[InformationRecord],
    *,
    trading_dates: Sequence[date],
    source_fetched_at: str,
) -> list[CapitalFlowSnapshot]:
    calendar = tuple(sorted(set(trading_dates)))
    position_by_date = {trade_date: index for index, trade_date in enumerate(calendar)}
    by_symbol: dict[str, list[InformationRecord]] = {}
    for record in records:
        if record.source == "akshare_fund_flow" and record.normalized_symbol is not None:
            by_symbol.setdefault(record.normalized_symbol, []).append(record)

    snapshots: list[CapitalFlowSnapshot] = []
    for symbol, symbol_records in sorted(by_symbol.items()):
        ordered = sorted(symbol_records, key=lambda record: record.published_at)
        seen_dates: set[date] = set()
        previous_position: int | None = None
        previous_streak: int | None = None
        for record in ordered:
            trade_date = record.published_at
            if trade_date in seen_dates:
                raise ValueError(f"duplicate capital-flow record for {symbol} on {trade_date.isoformat()}")
            seen_dates.add(trade_date)
            if trade_date not in position_by_date:
                raise ValueError(f"capital-flow date is outside the trading calendar: {trade_date.isoformat()}")
            main_net_inflow = _summary_float(record.summary, "main_net_inflow")
            current_position = position_by_date[trade_date]
            streak = _outflow_streak(
                main_net_inflow,
                current_position=current_position,
                previous_position=previous_position,
                previous_streak=previous_streak,
            )
            snapshots.append(
                CapitalFlowSnapshot(
                    symbol=symbol,
                    trade_date=trade_date,
                    available_date=trade_date,
                    source=record.source,
                    source_fetched_at=source_fetched_at,
                    values={
                        "main_net_inflow": main_net_inflow,
                        "main_outflow_days": streak,
                        "margin_financing_positive": None,
                    },
                )
            )
            previous_position = current_position
            previous_streak = streak
    return snapshots


def fundamental_row(snapshot: FundamentalSnapshot) -> dict[str, object]:
    return {
        "symbol": snapshot.symbol,
        "report_period": snapshot.report_period.isoformat() if snapshot.report_period else None,
        "available_date": snapshot.available_date.isoformat(),
        "source": snapshot.source,
        "source_fetched_at": snapshot.source_fetched_at,
        **snapshot.values,
    }


def capital_flow_row(snapshot: CapitalFlowSnapshot) -> dict[str, object]:
    return {
        "symbol": snapshot.symbol,
        "trade_date": snapshot.trade_date.isoformat(),
        "available_date": snapshot.available_date.isoformat(),
        "source": snapshot.source,
        "source_fetched_at": snapshot.source_fetched_at,
        **snapshot.values,
    }


def _valuation_events(records: Sequence[InformationRecord]) -> dict[date, dict[str, float | None]]:
    events: dict[date, dict[str, float | None]] = {}
    for record in sorted(records, key=lambda item: (item.published_at, item.title)):
        if record.metadata.get("record_kind") != "valuation":
            continue
        events[record.published_at] = {
            "pe": _summary_float(record.summary, "pe"),
            "pb": _summary_float(record.summary, "pb"),
        }
    return events


def _financial_events(
    records: Sequence[InformationRecord],
) -> dict[date, tuple[date, dict[str, float | None]]]:
    indicators: dict[date, dict[str, float | None]] = {}
    statements: dict[date, list[InformationRecord]] = {}
    for record in records:
        raw_period = record.metadata.get("report_period")
        if not isinstance(raw_period, str):
            continue
        report_period = date.fromisoformat(raw_period)
        if record.metadata.get("record_kind") == "financial_indicator":
            indicators[report_period] = {
                "roe": _summary_float(record.summary, "roe"),
                "growth": _summary_float(record.summary, "growth"),
                "goodwill_ratio": None,
            }
        elif record.source == "akshare_financial_statement":
            if not record.metadata.get("available_date_source"):
                raise ValueError("financial statement is missing available_date_source")
            statements.setdefault(report_period, []).append(record)

    events: dict[date, tuple[date, dict[str, float | None]]] = {}
    for report_period, period_statements in statements.items():
        available_date = max(record.published_at for record in period_statements)
        values = dict(
            indicators.get(
                report_period,
                {"roe": None, "growth": None, "goodwill_ratio": None},
            )
        )
        goodwill_ratio = _goodwill_ratio(period_statements)
        if goodwill_ratio is not None:
            values["goodwill_ratio"] = goodwill_ratio
        previous = events.get(available_date)
        if previous is None or report_period > previous[0]:
            events[available_date] = (report_period, values)
    return events


def _goodwill_ratio(records: Iterable[InformationRecord]) -> float | None:
    for record in records:
        goodwill = _summary_float(record.summary, "goodwill")
        total_assets = _summary_float(record.summary, "total_assets")
        if goodwill is not None and total_assets is not None and total_assets > 0:
            return round(goodwill / total_assets, 6)
    return None


def _summary_float(summary: str, field: str) -> float | None:
    values = _summary_values(summary)
    raw_value = values.get(field)
    return float(raw_value) if raw_value is not None else None


def _summary_values(summary: str) -> Mapping[str, str]:
    values: dict[str, str] = {}
    for part in summary.split(";"):
        if "=" not in part:
            continue
        key, value = (item.strip() for item in part.split("=", 1))
        if key and value:
            values[key] = value
    return values


def _outflow_streak(
    main_net_inflow: float | None,
    *,
    current_position: int,
    previous_position: int | None,
    previous_streak: int | None,
) -> int | None:
    if main_net_inflow is None:
        return None
    if main_net_inflow >= 0:
        return 0
    if previous_position is None:
        return 1 if current_position == 0 else None
    if current_position != previous_position + 1 or previous_streak is None:
        return None
    return previous_streak + 1
