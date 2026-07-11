from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping

from fintech_quant.backtesting import (
    AShareCostModel,
    PortfolioBacktestResult,
    load_corporate_actions_csv,
    run_portfolio_scored_baseline_backtest,
)
from fintech_quant.features import StockScore
from fintech_quant.data.research_dataset import load_daily_bars_csv
from fintech_quant.research.dataset import FeatureRow, ResearchDataset, SupplementalRow, load_research_dataset
from fintech_quant.research.risk_builder import PortfolioRiskState, build_risk_input
from fintech_quant.research.scoring import build_stock_scores
from fintech_quant.research.point_in_time import SupplementalAsOfIndex
from fintech_quant.risk import RiskInput, RiskLimits
from fintech_quant.strategies import ScoredBaselineStrategy
from fintech_quant.trading import TradeAction


@dataclass(frozen=True)
class ResearchRunConfig:
    run_id: str
    features_path: Path
    universe_path: Path
    execution_prices_path: Path | None = None
    corporate_actions_path: Path | None = None
    information_path: Path | None = None
    fundamentals_path: Path | None = None
    capital_flow_path: Path | None = None
    market_state_path: Path | None = None
    membership_path: Path | None = None
    require_point_in_time: bool = False
    initial_cash: float = 100000.0
    max_position_weight: float = 0.08
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    include_stamp_duty: bool = True
    slippage_rate: float = 0.0
    execution_delay_sessions: int = 1
    buy_threshold: float = 70.0
    min_score_confidence: float = 0.8
    max_portfolio_drawdown: float = 0.15
    max_single_position_drawdown: float = 0.08
    max_goodwill_ratio: float = 0.30
    max_pledge_ratio: float = 0.50
    max_main_outflow_days: int = 3
    broad_market_drop_threshold: int = 15

    def __post_init__(self) -> None:
        _require_positive("initial_cash", self.initial_cash)
        _require_positive_unit_ratio("max_position_weight", self.max_position_weight)
        _require_non_negative("commission_rate", self.commission_rate)
        _require_non_negative("minimum_commission", self.minimum_commission)
        _require_non_negative("slippage_rate", self.slippage_rate)
        _require_non_negative_int("execution_delay_sessions", self.execution_delay_sessions)
        _require_non_negative("buy_threshold", self.buy_threshold)
        _require_unit_ratio("min_score_confidence", self.min_score_confidence)
        _require_positive_unit_ratio("max_portfolio_drawdown", self.max_portfolio_drawdown)
        _require_positive_unit_ratio("max_single_position_drawdown", self.max_single_position_drawdown)
        _require_unit_ratio("max_goodwill_ratio", self.max_goodwill_ratio)
        _require_unit_ratio("max_pledge_ratio", self.max_pledge_ratio)
        _require_non_negative_int("max_main_outflow_days", self.max_main_outflow_days)
        _require_non_negative_int("broad_market_drop_threshold", self.broad_market_drop_threshold)


@dataclass(frozen=True)
class ResearchRunReport:
    run_id: str
    inputs: dict[str, str | None]
    strategy_config: dict[str, object]
    risk_limits: dict[str, float | int]
    universe_symbols: tuple[str, ...]
    date_range: tuple[str, str] | None
    scores: list[dict[str, object]]
    missing_fields: list[dict[str, object]]
    risk_warnings: list[dict[str, object]]
    risk_summary: dict[str, object]
    trades: list[dict[str, object]]
    corporate_actions: list[dict[str, object]]
    equity_curve: list[dict[str, object]]
    drawdown: dict[str, object]
    summary: dict[str, float | int | str]


def _require_positive(name: str, value: float) -> None:
    _require_finite_number(name, value)
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0")


def _require_non_negative(name: str, value: float) -> None:
    _require_finite_number(name, value)
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to 0")


def _require_unit_ratio(name: str, value: float) -> None:
    _require_finite_number(name, value)
    if value < 0 or value > 1:
        raise ValueError(f"{name} must be between 0 and 1")


def _require_positive_unit_ratio(name: str, value: float) -> None:
    _require_finite_number(name, value)
    if value <= 0 or value > 1:
        raise ValueError(f"{name} must be greater than 0 and less than or equal to 1")


def _require_finite_number(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")


def _require_non_negative_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to 0")


def run_research_baseline(config: ResearchRunConfig) -> ResearchRunReport:
    dataset = load_research_dataset(
        config.features_path,
        config.universe_path,
        fundamentals_path=config.fundamentals_path,
        capital_flow_path=config.capital_flow_path,
        market_state_path=config.market_state_path,
        information_path=config.information_path,
        membership_path=config.membership_path,
        require_point_in_time=config.require_point_in_time,
    )
    scores = build_stock_scores(dataset)
    risk_inputs = _build_static_risk_inputs(dataset, config.initial_cash)
    strategy = ScoredBaselineStrategy(
        buy_threshold=config.buy_threshold,
        min_confidence=config.min_score_confidence,
    )
    result = run_portfolio_scored_baseline_backtest(
        [_bar_from_feature(row) for row in dataset.features],
        scores,
        execution_bars=(
            load_daily_bars_csv(config.execution_prices_path)
            if config.execution_prices_path is not None
            else None
        ),
        corporate_actions=(
            load_corporate_actions_csv(config.corporate_actions_path)
            if config.corporate_actions_path is not None
            else ()
        ),
        risk_inputs=risk_inputs,
        initial_cash=config.initial_cash,
        max_position_weight=config.max_position_weight,
        commission_rate=config.commission_rate,
        slippage_rate=config.slippage_rate,
        strategy=strategy,
        risk_limits=_risk_limits_from_config(config),
        execution_delay_sessions=config.execution_delay_sessions,
        cost_model=AShareCostModel(
            commission_rate=config.commission_rate,
            minimum_commission=config.minimum_commission,
            include_stamp_duty=config.include_stamp_duty,
        ),
    )
    return _report_from_result(config, dataset, scores, result)


def write_run_report(report: ResearchRunReport, output_root: Path) -> Path:
    output_dir = output_root / report.run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "run_report.json"
    report_path.write_text(json.dumps(_report_to_json(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report_path


def _build_static_risk_inputs(
    dataset: ResearchDataset,
    initial_cash: float,
) -> dict[tuple[date, str], RiskInput]:
    risk_inputs: dict[tuple[date, str], RiskInput] = {}
    neutral_state = PortfolioRiskState(equity=initial_cash, rolling_peak=initial_cash, positions={})
    trading_dates = tuple(sorted({row.trade_date for row in dataset.features}))
    fundamentals_index = SupplementalAsOfIndex(
        dataset.fundamentals.values(),
        trading_dates=trading_dates,
        allow_undated=not dataset.require_point_in_time,
    )
    capital_flow_index = SupplementalAsOfIndex(
        dataset.capital_flow.values(),
        trading_dates=trading_dates,
        allow_undated=not dataset.require_point_in_time,
    )
    for row in dataset.features:
        fundamentals = _row_values(
            fundamentals_index.lookup(row.symbol, row.trade_date, max_age_days=180)
        )
        capital_flow = _row_values(
            capital_flow_index.lookup(row.symbol, row.trade_date, max_age_sessions=3)
        )
        market_state = dataset.market_state.get(row.trade_date)
        risk_inputs[(row.trade_date, row.symbol)] = build_risk_input(
            row.symbol,
            row.trade_date,
            float(row.values["close"]),
            neutral_state,
            fundamentals=fundamentals,
            capital_flow=capital_flow,
            market_state=market_state.values if market_state else None,
            sector=_text_or_none(row.values.get("sector")),
            information_records=dataset.information_records,
        )
    return risk_inputs


def _row_values(row: SupplementalRow | None) -> Mapping[str, object] | None:
    return row.values if row else None


def _bar_from_feature(row: FeatureRow) -> dict[str, object]:
    bar = {
        "symbol": row.symbol,
        "trade_date": row.trade_date,
        "open": row.values.get("open"),
        "high": row.values.get("high"),
        "low": row.values.get("low"),
        "close": row.values["close"],
        "volume": row.values.get("volume"),
        "amount": row.values.get("amount"),
        "source": row.values.get("source", "features"),
    }
    for flag in ("is_suspended", "suspended", "limit_up", "is_limit_up", "limit_down", "is_limit_down"):
        if flag in row.values:
            bar[flag] = row.values[flag]
    return bar


def _text_or_none(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _report_from_result(
    config: ResearchRunConfig,
    dataset: ResearchDataset,
    scores: Mapping[tuple[date, str], StockScore],
    result: PortfolioBacktestResult,
) -> ResearchRunReport:
    score_rows = [_score_to_json(trade_date, symbol, score) for (trade_date, symbol), score in sorted(scores.items())]
    risk_warnings = [_risk_warning_to_json(warning) for warning in result.risk_warnings]
    return ResearchRunReport(
        run_id=config.run_id,
        inputs={
            "features": str(config.features_path),
            "execution_prices": (
                str(config.execution_prices_path) if config.execution_prices_path else None
            ),
            "corporate_actions": (
                str(config.corporate_actions_path) if config.corporate_actions_path else None
            ),
            "universe": str(config.universe_path),
            "information": str(config.information_path) if config.information_path else None,
            "fundamentals": str(config.fundamentals_path) if config.fundamentals_path else None,
            "capital_flow": str(config.capital_flow_path) if config.capital_flow_path else None,
            "market_state": str(config.market_state_path) if config.market_state_path else None,
            "membership": str(config.membership_path) if config.membership_path else None,
        },
        strategy_config={
            "require_point_in_time": config.require_point_in_time,
            "buy_threshold": config.buy_threshold,
            "min_confidence": config.min_score_confidence,
            "execution_delay_sessions": float(config.execution_delay_sessions),
            "commission_rate": config.commission_rate,
            "minimum_commission": config.minimum_commission,
            "slippage_rate": config.slippage_rate,
            "include_stamp_duty": config.include_stamp_duty,
        },
        risk_limits=_risk_limits_to_json(_risk_limits_from_config(config)),
        universe_symbols=dataset.universe_symbols,
        date_range=_date_range(dataset.features),
        scores=score_rows,
        missing_fields=[
            {"trade_date": row["trade_date"], "symbol": row["symbol"], "missing_fields": row["missing_fields"]}
            for row in score_rows
            if row["missing_fields"]
        ],
        risk_warnings=risk_warnings,
        risk_summary=_risk_summary(risk_warnings),
        trades=[_trade_to_json(trade) for trade in result.trades],
        corporate_actions=[
            _corporate_action_to_json(action) for action in result.corporate_actions
        ],
        equity_curve=[_equity_to_json(point) for point in result.equity_curve],
        drawdown={
            "max_drawdown": round(result.drawdown.max_drawdown, 6),
            "max_drawdown_start": (
                result.drawdown.max_drawdown_start.isoformat() if result.drawdown.max_drawdown_start else None
            ),
            "max_drawdown_end": (
                result.drawdown.max_drawdown_end.isoformat() if result.drawdown.max_drawdown_end else None
            ),
            "recovery_date": result.drawdown.recovery_date.isoformat() if result.drawdown.recovery_date else None,
            "liquidation_date": result.drawdown.liquidation_date.isoformat() if result.drawdown.liquidation_date else None,
            "current_drawdown": round(result.drawdown.current_drawdown, 6),
            "current_drawdown_start": (
                result.drawdown.current_drawdown_start.isoformat() if result.drawdown.current_drawdown_start else None
            ),
            "current_underwater_days": result.drawdown.current_underwater_days,
            "points": [_drawdown_point_to_json(point) for point in result.drawdown.points],
            "episodes": [_drawdown_episode_to_json(episode) for episode in (result.drawdown.episodes or [])],
        },
        summary=result.summary,
    )


def _date_range(features: list[FeatureRow]) -> tuple[str, str] | None:
    if not features:
        return None
    dates = [row.trade_date for row in features]
    return (min(dates).isoformat(), max(dates).isoformat())


def _score_to_json(trade_date: date, symbol: str, score: StockScore) -> dict[str, object]:
    return {
        "trade_date": trade_date.isoformat(),
        "symbol": symbol,
        "total": score.total,
        "confidence": score.confidence,
        "missing_fields": list(score.missing_fields),
        "components": {
            name: {
                "score": component.score,
                "max_score": component.max_score,
                "reasons": list(component.reasons),
            }
            for name, component in sorted(score.components.items())
        },
    }


def _risk_warning_to_json(warning: object) -> dict[str, object]:
    return {
        "trade_date": warning.trade_date.isoformat(),
        "symbol": warning.symbol,
        "layer": warning.layer,
        "rule": warning.rule,
        "action": warning.action,
        "message": warning.message,
        "observed_value": warning.observed_value,
        "threshold_value": warning.threshold_value,
    }


def _risk_limits_from_config(config: ResearchRunConfig) -> RiskLimits:
    return RiskLimits(
        max_position_weight=config.max_position_weight,
        max_portfolio_drawdown=config.max_portfolio_drawdown,
        max_single_position_drawdown=config.max_single_position_drawdown,
        max_goodwill_ratio=config.max_goodwill_ratio,
        max_pledge_ratio=config.max_pledge_ratio,
        max_main_outflow_days=config.max_main_outflow_days,
        broad_market_drop_threshold=config.broad_market_drop_threshold,
    )


def _risk_limits_to_json(limits: RiskLimits) -> dict[str, float | int]:
    return {
        "max_position_weight": limits.max_position_weight,
        "max_portfolio_drawdown": limits.max_portfolio_drawdown,
        "max_single_position_drawdown": limits.max_single_position_drawdown,
        "max_goodwill_ratio": limits.max_goodwill_ratio,
        "max_pledge_ratio": limits.max_pledge_ratio,
        "max_main_outflow_days": limits.max_main_outflow_days,
        "broad_market_drop_threshold": limits.broad_market_drop_threshold,
    }


def _risk_summary(warnings: list[dict[str, object]]) -> dict[str, object]:
    return {
        "total_warnings": len(warnings),
        "by_layer": _count_by(warnings, "layer"),
        "by_action": _count_by(warnings, "action"),
        "by_rule": _count_by(warnings, "rule"),
    }


def _count_by(rows: list[dict[str, object]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row[field])
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _trade_to_json(trade: object) -> dict[str, object]:
    action = trade.action.value if isinstance(trade.action, TradeAction) else str(trade.action)
    row = {
        "trade_date": trade.trade_date.isoformat(),
        "signal_date": trade.signal_date.isoformat(),
        "symbol": trade.symbol,
        "action": action,
        "price": trade.price,
        "shares": trade.shares,
        "notional": trade.notional,
        "commission": trade.commission,
        "stamp_duty": trade.stamp_duty,
        "total_cost": trade.total_cost,
        "cash": trade.cash,
        "position": trade.position,
        "reason": trade.reason,
    }
    realized_pnl = getattr(trade, "realized_pnl", None)
    if realized_pnl is not None:
        row["realized_pnl"] = realized_pnl
    return row


def _equity_to_json(point: object) -> dict[str, object]:
    return {
        "trade_date": point.trade_date.isoformat(),
        "cash": point.cash,
        "positions_value": point.positions_value,
        "equity": point.equity,
    }


def _corporate_action_to_json(action: object) -> dict[str, object]:
    return {
        "symbol": action.symbol,
        "ex_date": action.ex_date.isoformat(),
        "cash_dividend_per_share": action.cash_dividend_per_share,
        "share_multiplier": action.share_multiplier,
        "shares_before": action.shares_before,
        "shares_after": action.shares_after,
        "cash_delta": action.cash_delta,
        "source": action.source,
    }


def _drawdown_point_to_json(point: object) -> dict[str, object]:
    return {
        "trade_date": point.trade_date.isoformat(),
        "equity": point.equity,
        "rolling_peak": point.rolling_peak,
        "drawdown": round(point.drawdown, 6),
    }


def _drawdown_episode_to_json(episode: object) -> dict[str, object]:
    return {
        "start_date": episode.start_date.isoformat(),
        "trough_date": episode.trough_date.isoformat(),
        "recovery_date": episode.recovery_date.isoformat() if episode.recovery_date else None,
        "peak_equity": round(episode.peak_equity, 6),
        "trough_equity": round(episode.trough_equity, 6),
        "max_drawdown": round(episode.max_drawdown, 6),
        "duration_days": episode.duration_days,
        "recovery_days": episode.recovery_days,
    }


def _report_to_json(report: ResearchRunReport) -> dict[str, object]:
    return {
        "run_id": report.run_id,
        "inputs": report.inputs,
        "strategy_config": report.strategy_config,
        "risk_limits": report.risk_limits,
        "universe_symbols": list(report.universe_symbols),
        "date_range": list(report.date_range) if report.date_range else None,
        "scores": report.scores,
        "missing_fields": report.missing_fields,
        "risk_warnings": report.risk_warnings,
        "risk_summary": report.risk_summary,
        "trades": report.trades,
        "corporate_actions": report.corporate_actions,
        "equity_curve": report.equity_curve,
        "drawdown": report.drawdown,
        "summary": report.summary,
    }
