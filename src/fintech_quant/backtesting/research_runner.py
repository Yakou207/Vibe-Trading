from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence

from fintech_quant.backtesting.drawdown import DrawdownResult, EquityPoint, calculate_drawdown
from fintech_quant.features import StockScore
from fintech_quant.risk import RiskInput, RiskWarning, evaluate_risk
from fintech_quant.strategies.scored_baseline import ScoredBaselineStrategy
from fintech_quant.trading import TradeAction


@dataclass(frozen=True)
class BacktestTrade:
    trade_date: date
    symbol: str
    action: TradeAction
    price: float
    shares: int
    cash: float
    position: int
    reason: str


@dataclass(frozen=True)
class DailyEquity:
    trade_date: date
    cash: float
    position: int
    close: float
    equity: float


@dataclass(frozen=True)
class DatedRiskWarning:
    trade_date: date
    layer: str
    rule: str
    action: str
    message: str


@dataclass(frozen=True)
class ResearchBacktestResult:
    trades: list[BacktestTrade]
    equity_curve: list[DailyEquity]
    risk_warnings: list[DatedRiskWarning]
    drawdown: DrawdownResult
    summary: dict[str, float | int]


def run_scored_baseline_backtest(
    bars: Sequence[Mapping[str, object]],
    scores: Mapping[date, StockScore],
    *,
    risk_inputs: Mapping[date, RiskInput] | None = None,
    initial_cash: float = 100000.0,
    strategy: ScoredBaselineStrategy | None = None,
) -> ResearchBacktestResult:
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    if not bars:
        raise ValueError("bars must contain at least one daily bar")

    active_strategy = strategy or ScoredBaselineStrategy()
    risk_by_date = risk_inputs or {}
    cash = float(initial_cash)
    position = 0
    trades: list[BacktestTrade] = []
    equity_curve: list[DailyEquity] = []
    risk_warnings: list[DatedRiskWarning] = []

    for bar in sorted(bars, key=lambda item: _bar_date(item)):
        trade_date = _bar_date(bar)
        symbol = str(bar["symbol"])
        close = _bar_close(bar)
        score = scores.get(trade_date)
        if score is None:
            raise ValueError(f"Missing score for {trade_date.isoformat()}")

        risk = evaluate_risk(risk_by_date.get(trade_date, RiskInput()))
        risk_warnings.extend(_dated_warnings(trade_date, risk.warnings))
        decision = active_strategy.decide({"score": score, "risk_action": risk.action})

        if decision.action is TradeAction.BUY and position == 0:
            shares = int(cash // close)
            if shares > 0:
                cash -= shares * close
                position += shares
                trades.append(
                    BacktestTrade(
                        trade_date=trade_date,
                        symbol=symbol,
                        action=TradeAction.BUY,
                        price=close,
                        shares=shares,
                        cash=cash,
                        position=position,
                        reason=decision.reason,
                    )
                )
        elif decision.action is TradeAction.SELL and position > 0:
            shares = position
            cash += shares * close
            position = 0
            trades.append(
                BacktestTrade(
                    trade_date=trade_date,
                    symbol=symbol,
                    action=TradeAction.SELL,
                    price=close,
                    shares=shares,
                    cash=cash,
                    position=position,
                    reason=decision.reason,
                )
            )

        equity_curve.append(
            DailyEquity(
                trade_date=trade_date,
                cash=round(cash, 6),
                position=position,
                close=close,
                equity=round(cash + position * close, 6),
            )
        )

    drawdown = calculate_drawdown(
        [EquityPoint(point.trade_date, point.equity) for point in equity_curve]
    )
    ending_equity = equity_curve[-1].equity
    return ResearchBacktestResult(
        trades=trades,
        equity_curve=equity_curve,
        risk_warnings=risk_warnings,
        drawdown=drawdown,
        summary={
            "initial_cash": float(initial_cash),
            "ending_equity": ending_equity,
            "total_return": round((ending_equity - initial_cash) / initial_cash, 6),
            "max_drawdown": round(drawdown.max_drawdown, 6),
            "trade_count": len(trades),
            "risk_warning_count": len(risk_warnings),
        },
    )


def _bar_date(bar: Mapping[str, object]) -> date:
    raw_date = bar.get("trade_date")
    if isinstance(raw_date, date):
        return raw_date
    if isinstance(raw_date, str):
        return date.fromisoformat(raw_date)
    raise ValueError("bar is missing trade_date")


def _bar_close(bar: Mapping[str, object]) -> float:
    if "close" not in bar:
        raise ValueError("bar is missing close")
    close = float(bar["close"])
    if close <= 0:
        raise ValueError("bar close must be positive")
    return close


def _dated_warnings(trade_date: date, warnings: list[RiskWarning]) -> list[DatedRiskWarning]:
    return [
        DatedRiskWarning(
            trade_date=trade_date,
            layer=warning.layer,
            rule=warning.rule,
            action=warning.action.value,
            message=warning.message,
        )
        for warning in warnings
    ]
