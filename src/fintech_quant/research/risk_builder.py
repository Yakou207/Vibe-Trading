from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence

from fintech_quant.information import InformationRecord
from fintech_quant.research.scoring import NEGATIVE_RISK_TAGS
from fintech_quant.risk import RiskInput


@dataclass(frozen=True)
class PositionState:
    shares: int = 0
    cost_basis: float = 0.0
    market_value: float = 0.0


@dataclass(frozen=True)
class PortfolioRiskState:
    equity: float
    rolling_peak: float
    positions: dict[str, PositionState]


def build_risk_input(
    symbol: str,
    trade_date: date,
    close: float,
    portfolio_state: PortfolioRiskState,
    *,
    fundamentals: Mapping[str, object] | None = None,
    capital_flow: Mapping[str, object] | None = None,
    market_state: Mapping[str, object] | None = None,
    sector: str | None = None,
    information_records: Sequence[InformationRecord] = (),
) -> RiskInput:
    fundamental_values = fundamentals or {}
    capital_values = capital_flow or {}
    market_values = market_state or {}
    position = portfolio_state.positions.get(symbol, PositionState())
    return RiskInput(
        position_weight=_position_weight(position.market_value, portfolio_state.equity),
        portfolio_drawdown=_portfolio_drawdown(portfolio_state.equity, portfolio_state.rolling_peak),
        single_position_drawdown=_single_position_drawdown(position, close),
        st_warning=_bool(fundamental_values.get("st_warning"))
        or _has_symbol_tag(symbol, trade_date, information_records, "st_warning", sector),
        negative_event_count=_negative_event_count(symbol, trade_date, information_records, sector),
        goodwill_ratio=_float(fundamental_values.get("goodwill_ratio")),
        pledge_ratio=_float(fundamental_values.get("pledge_ratio")),
        main_outflow_days=_int(capital_values.get("main_outflow_days")),
        index_below_annual_ma=_bool(market_values.get("index_below_annual_ma")),
        broad_market_drop_gt_3pct_count=_int(market_values.get("broad_market_drop_gt_3pct_count")),
    )


def _has_symbol_tag(
    symbol: str,
    trade_date: date,
    records: Sequence[InformationRecord],
    tag: str,
    sector: str | None = None,
) -> bool:
    return any(
        (record.normalized_symbol == symbol or (sector is not None and record.symbol is None and record.sector == sector))
        and record.published_at <= trade_date
        and tag in record.risk_tags
        for record in records
    )


def _negative_event_count(
    symbol: str,
    trade_date: date,
    records: Sequence[InformationRecord],
    sector: str | None = None,
) -> int:
    return sum(
        1
        for record in records
        if (record.normalized_symbol == symbol or (sector is not None and record.symbol is None and record.sector == sector))
        and record.published_at <= trade_date
        and any(tag in NEGATIVE_RISK_TAGS for tag in record.risk_tags)
        and "st_warning" not in record.risk_tags
    )


def _position_weight(market_value: float, equity: float) -> float:
    if equity <= 0:
        return 0.0
    return round(market_value / equity, 6)


def _portfolio_drawdown(equity: float, rolling_peak: float) -> float:
    if rolling_peak <= 0:
        return 0.0
    return round(max(0.0, (rolling_peak - equity) / rolling_peak), 6)


def _single_position_drawdown(position: PositionState, close: float) -> float:
    if position.shares <= 0 or position.cost_basis <= 0:
        return 0.0
    return round(max(0.0, (position.cost_basis - close) / position.cost_basis), 6)


def _float(value: object) -> float:
    if value is None:
        return 0.0
    return float(value)


def _int(value: object) -> int:
    if value is None:
        return 0
    return int(value)


def _bool(value: object) -> bool:
    if value is None:
        return False
    return bool(value)
