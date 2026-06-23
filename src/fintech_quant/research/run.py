from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping

from fintech_quant.backtesting import PortfolioBacktestResult, run_portfolio_scored_baseline_backtest
from fintech_quant.features import StockScore
from fintech_quant.research.dataset import FeatureRow, ResearchDataset, SupplementalRow, load_research_dataset
from fintech_quant.research.risk_builder import PortfolioRiskState, build_risk_input
from fintech_quant.research.scoring import build_stock_scores
from fintech_quant.risk import RiskInput
from fintech_quant.trading import TradeAction


@dataclass(frozen=True)
class ResearchRunConfig:
    run_id: str
    features_path: Path
    universe_path: Path
    information_path: Path | None = None
    fundamentals_path: Path | None = None
    capital_flow_path: Path | None = None
    market_state_path: Path | None = None
    initial_cash: float = 100000.0
    max_position_weight: float = 0.08
    commission_rate: float = 0.0003
    slippage_rate: float = 0.0


@dataclass(frozen=True)
class ResearchRunReport:
    run_id: str
    inputs: dict[str, str | None]
    universe_symbols: tuple[str, ...]
    date_range: tuple[str, str] | None
    scores: list[dict[str, object]]
    missing_fields: list[dict[str, object]]
    risk_warnings: list[dict[str, object]]
    trades: list[dict[str, object]]
    equity_curve: list[dict[str, object]]
    drawdown: dict[str, object]
    summary: dict[str, float | int]


def run_research_baseline(config: ResearchRunConfig) -> ResearchRunReport:
    dataset = load_research_dataset(
        config.features_path,
        config.universe_path,
        fundamentals_path=config.fundamentals_path,
        capital_flow_path=config.capital_flow_path,
        market_state_path=config.market_state_path,
        information_path=config.information_path,
    )
    scores = build_stock_scores(dataset)
    risk_inputs = _build_static_risk_inputs(dataset, config.initial_cash)
    result = run_portfolio_scored_baseline_backtest(
        [_bar_from_feature(row) for row in dataset.features],
        scores,
        risk_inputs=risk_inputs,
        initial_cash=config.initial_cash,
        max_position_weight=config.max_position_weight,
        commission_rate=config.commission_rate,
        slippage_rate=config.slippage_rate,
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
    for row in dataset.features:
        fundamentals = _supplement_values(dataset.fundamentals, row.symbol, row.trade_date)
        capital_flow = _supplement_values(dataset.capital_flow, row.symbol, row.trade_date)
        market_state = dataset.market_state.get(row.trade_date)
        risk_inputs[(row.trade_date, row.symbol)] = build_risk_input(
            row.symbol,
            row.trade_date,
            float(row.values["close"]),
            neutral_state,
            fundamentals=fundamentals,
            capital_flow=capital_flow,
            market_state=market_state.values if market_state else None,
            information_records=dataset.information_records,
        )
    return risk_inputs


def _supplement_values(
    rows: Mapping[tuple[str, date | None], SupplementalRow],
    symbol: str,
    trade_date: date,
) -> Mapping[str, object] | None:
    row = rows.get((symbol, trade_date)) or rows.get((symbol, None))
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


def _report_from_result(
    config: ResearchRunConfig,
    dataset: ResearchDataset,
    scores: Mapping[tuple[date, str], StockScore],
    result: PortfolioBacktestResult,
) -> ResearchRunReport:
    score_rows = [_score_to_json(trade_date, symbol, score) for (trade_date, symbol), score in sorted(scores.items())]
    return ResearchRunReport(
        run_id=config.run_id,
        inputs={
            "features": str(config.features_path),
            "universe": str(config.universe_path),
            "information": str(config.information_path) if config.information_path else None,
            "fundamentals": str(config.fundamentals_path) if config.fundamentals_path else None,
            "capital_flow": str(config.capital_flow_path) if config.capital_flow_path else None,
            "market_state": str(config.market_state_path) if config.market_state_path else None,
        },
        universe_symbols=dataset.universe_symbols,
        date_range=_date_range(dataset.features),
        scores=score_rows,
        missing_fields=[
            {"trade_date": row["trade_date"], "symbol": row["symbol"], "missing_fields": row["missing_fields"]}
            for row in score_rows
            if row["missing_fields"]
        ],
        risk_warnings=[_risk_warning_to_json(warning) for warning in result.risk_warnings],
        trades=[_trade_to_json(trade) for trade in result.trades],
        equity_curve=[_equity_to_json(point) for point in result.equity_curve],
        drawdown={
            "max_drawdown": round(result.drawdown.max_drawdown, 6),
            "liquidation_date": result.drawdown.liquidation_date.isoformat() if result.drawdown.liquidation_date else None,
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
    }


def _trade_to_json(trade: object) -> dict[str, object]:
    action = trade.action.value if isinstance(trade.action, TradeAction) else str(trade.action)
    return {
        "trade_date": trade.trade_date.isoformat(),
        "symbol": trade.symbol,
        "action": action,
        "price": trade.price,
        "shares": trade.shares,
        "notional": trade.notional,
        "commission": trade.commission,
        "cash": trade.cash,
        "position": trade.position,
        "reason": trade.reason,
    }


def _equity_to_json(point: object) -> dict[str, object]:
    return {
        "trade_date": point.trade_date.isoformat(),
        "cash": point.cash,
        "positions_value": point.positions_value,
        "equity": point.equity,
    }


def _report_to_json(report: ResearchRunReport) -> dict[str, object]:
    return {
        "run_id": report.run_id,
        "inputs": report.inputs,
        "universe_symbols": list(report.universe_symbols),
        "date_range": list(report.date_range) if report.date_range else None,
        "scores": report.scores,
        "missing_fields": report.missing_fields,
        "risk_warnings": report.risk_warnings,
        "trades": report.trades,
        "equity_curve": report.equity_curve,
        "drawdown": report.drawdown,
        "summary": report.summary,
    }
