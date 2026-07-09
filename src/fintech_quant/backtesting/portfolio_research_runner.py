from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Mapping, Sequence

from fintech_quant.backtesting.constraints import AShareTradingConstraints
from fintech_quant.backtesting.drawdown import DrawdownResult, EquityPoint, calculate_drawdown
from fintech_quant.features import StockScore
from fintech_quant.risk import RiskAction, RiskInput, RiskLimits, RiskWarning, evaluate_risk
from fintech_quant.strategies.scored_baseline import ScoredBaselineStrategy
from fintech_quant.strategies.base import Strategy
from fintech_quant.trading import TradeAction


@dataclass(frozen=True)
class PortfolioBacktestTrade:
    trade_date: date
    symbol: str
    action: TradeAction
    price: float
    shares: int
    notional: float
    commission: float
    cash: float
    position: int
    reason: str
    realized_pnl: float | None = None


@dataclass(frozen=True)
class PortfolioDailyEquity:
    trade_date: date
    cash: float
    positions_value: float
    equity: float


@dataclass(frozen=True)
class PortfolioDatedRiskWarning:
    trade_date: date
    symbol: str
    layer: str
    rule: str
    action: str
    message: str
    observed_value: object | None = None
    threshold_value: object | None = None


@dataclass(frozen=True)
class PortfolioBacktestResult:
    trades: list[PortfolioBacktestTrade]
    equity_curve: list[PortfolioDailyEquity]
    risk_warnings: list[PortfolioDatedRiskWarning]
    drawdown: DrawdownResult
    summary: dict[str, float | int | str]


@dataclass
class _Position:
    shares: int = 0
    cost_basis: float = 0.0


def run_portfolio_scored_baseline_backtest(
    bars: Sequence[Mapping[str, object]],
    scores: Mapping[tuple[date, str], StockScore],
    *,
    risk_inputs: Mapping[tuple[date, str], RiskInput] | None = None,
    initial_cash: float = 100000.0,
    max_position_weight: float = 0.08,
    lot_size: int = 100,
    commission_rate: float = 0.0003,
    slippage_rate: float = 0.0,
    constraints: AShareTradingConstraints | None = None,
    strategy: Strategy | None = None,
    strategy_state_overlays: Mapping[tuple[date, str], Mapping[str, object]] | None = None,
    risk_limits: RiskLimits | None = None,
) -> PortfolioBacktestResult:
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    if lot_size <= 0:
        raise ValueError("lot_size must be positive")
    active_constraints = replace(constraints, lot_size=lot_size) if constraints else AShareTradingConstraints(lot_size=lot_size)
    ordered = sorted(bars, key=lambda item: (_bar_date(item), str(item["symbol"])))
    if not ordered:
        raise ValueError("bars must contain at least one daily bar")

    active_strategy = strategy or ScoredBaselineStrategy()
    risk_by_key = risk_inputs or {}
    overlays_by_key = strategy_state_overlays or {}
    active_risk_limits = (
        replace(risk_limits, max_position_weight=max_position_weight)
        if risk_limits
        else RiskLimits(max_position_weight=max_position_weight)
    )
    cash = float(initial_cash)
    positions: dict[str, _Position] = {}
    trades: list[PortfolioBacktestTrade] = []
    warnings: list[PortfolioDatedRiskWarning] = []
    equity_curve: list[PortfolioDailyEquity] = []
    total_turnover = 0.0
    closed_wins = 0
    closed_count = 0
    rolling_peak = float(initial_cash)

    for trade_date, daily_bars in _group_by_date(ordered):
        close_by_symbol = {str(bar["symbol"]): _bar_close(bar) for bar in daily_bars}
        bought_today: set[str] = set()
        starting_equity = _equity(cash, positions, close_by_symbol)
        rolling_peak = max(rolling_peak, starting_equity)

        for bar in daily_bars:
            symbol = str(bar["symbol"])
            close = _bar_close(bar)
            score = scores.get((trade_date, symbol))
            position = positions.get(symbol, _Position())
            risk_input = _merge_risk_inputs(
                risk_by_key.get((trade_date, symbol), RiskInput()),
                _dynamic_risk_input(close, position, starting_equity, rolling_peak, commission_rate),
            )
            risk = evaluate_risk(risk_input, active_risk_limits)
            warnings.extend(_dated_warnings(trade_date, symbol, risk.warnings))

            if score is None:
                if (
                    position.shares > 0
                    and _can_sell(bar, active_constraints, symbol in bought_today)
                    and risk.action in {RiskAction.REDUCE, RiskAction.LIQUIDATE}
                ):
                    trade, cash, notional, closed_win = _sell_position(
                        trade_date=trade_date,
                        symbol=symbol,
                        close=close,
                        position=position,
                        cash=cash,
                        commission_rate=commission_rate,
                        slippage_rate=slippage_rate,
                        reason=f"Risk action {risk.action.value} overrides missing score.",
                    )
                    total_turnover += notional
                    closed_count += 1
                    if closed_win:
                        closed_wins += 1
                    trades.append(trade)
                    positions.pop(symbol, None)
                continue

            overlay_state = overlays_by_key.get((trade_date, symbol), {})
            state = {
                "score": score,
                "risk_action": risk.action,
                "position_quantity": position.shares,
            }
            state.update(overlay_state)
            decision = active_strategy.decide(state)

            if decision.action is TradeAction.SELL and position.shares > 0 and _can_sell(bar, active_constraints, symbol in bought_today):
                trade, cash, notional, closed_win = _sell_position(
                    trade_date=trade_date,
                    symbol=symbol,
                    close=close,
                    position=position,
                    cash=cash,
                    commission_rate=commission_rate,
                    slippage_rate=slippage_rate,
                    reason=decision.reason,
                )
                total_turnover += notional
                closed_count += 1
                if closed_win:
                    closed_wins += 1
                trades.append(trade)
                positions.pop(symbol, None)
                continue

            if (
                decision.action is TradeAction.BUY
                and position.shares == 0
                and _can_buy(bar, active_constraints)
                and risk.action not in {RiskAction.REDUCE, RiskAction.LIQUIDATE}
            ):
                buy_price = round(close * (1.0 + slippage_rate), 6)
                target_weight = max_position_weight
                if overlay_state:
                    target_weight *= _decision_weight(decision.confidence)
                max_notional = min(cash, starting_equity * target_weight)
                shares = _round_lot(int(max_notional // buy_price), active_constraints.lot_size)
                if shares <= 0:
                    continue
                notional = round(shares * buy_price, 6)
                commission = round(notional * commission_rate, 6)
                while shares > 0 and notional + commission > cash:
                    shares -= active_constraints.lot_size
                    notional = round(shares * buy_price, 6)
                    commission = round(notional * commission_rate, 6)
                if shares <= 0:
                    continue
                cash -= notional + commission
                total_turnover += notional
                positions[symbol] = _Position(shares=shares, cost_basis=buy_price)
                bought_today.add(symbol)
                trades.append(
                    PortfolioBacktestTrade(
                        trade_date=trade_date,
                        symbol=symbol,
                        action=TradeAction.BUY,
                        price=buy_price,
                        shares=shares,
                        notional=notional,
                        commission=commission,
                        cash=round(cash, 6),
                        position=shares,
                        reason=decision.reason,
                    )
                )

        positions_value = _positions_value(positions, close_by_symbol)
        equity_curve.append(
            PortfolioDailyEquity(
                trade_date=trade_date,
                cash=round(cash, 6),
                positions_value=round(positions_value, 6),
                equity=round(cash + positions_value, 6),
            )
        )

    drawdown = calculate_drawdown([EquityPoint(point.trade_date, point.equity) for point in equity_curve])
    ending_equity = equity_curve[-1].equity
    return PortfolioBacktestResult(
        trades=trades,
        equity_curve=equity_curve,
        risk_warnings=warnings,
        drawdown=drawdown,
        summary={
            "initial_cash": float(initial_cash),
            "ending_equity": ending_equity,
            "total_return": round((ending_equity - initial_cash) / initial_cash, 6),
            "max_drawdown": round(drawdown.max_drawdown, 6),
            "trade_count": len(trades),
            "risk_warning_count": len(warnings),
            "turnover": round(total_turnover / initial_cash, 6),
            "win_rate": round(closed_wins / closed_count, 6) if closed_count else 0.0,
            "win_rate_basis": "closed_trades_realized_pnl",
            "win_rate_sample_count": closed_count,
        },
    )


def _group_by_date(rows: Sequence[Mapping[str, object]]) -> list[tuple[date, list[Mapping[str, object]]]]:
    grouped: dict[date, list[Mapping[str, object]]] = {}
    for row in rows:
        grouped.setdefault(_bar_date(row), []).append(row)
    return [(trade_date, grouped[trade_date]) for trade_date in sorted(grouped)]


def _equity(cash: float, positions: Mapping[str, _Position], close_by_symbol: Mapping[str, float]) -> float:
    return cash + _positions_value(positions, close_by_symbol)


def _positions_value(positions: Mapping[str, _Position], close_by_symbol: Mapping[str, float]) -> float:
    return sum(position.shares * close_by_symbol.get(symbol, position.cost_basis) for symbol, position in positions.items())


def _can_buy(bar: Mapping[str, object], constraints: AShareTradingConstraints) -> bool:
    if constraints.suspension_filter_required and _truthy_bar_flag(bar, "is_suspended", "suspended"):
        return False
    if constraints.price_limit_required and _truthy_bar_flag(bar, "limit_up", "is_limit_up"):
        return False
    return True


def _can_sell(bar: Mapping[str, object], constraints: AShareTradingConstraints, bought_today: bool) -> bool:
    if constraints.t_plus_one and bought_today:
        return False
    if constraints.suspension_filter_required and _truthy_bar_flag(bar, "is_suspended", "suspended"):
        return False
    if constraints.price_limit_required and _truthy_bar_flag(bar, "limit_down", "is_limit_down"):
        return False
    return True


def _truthy_bar_flag(bar: Mapping[str, object], *keys: str) -> bool:
    return any(bool(bar.get(key)) for key in keys)


def _dynamic_risk_input(
    close: float,
    position: _Position,
    equity: float,
    rolling_peak: float,
    commission_rate: float,
) -> RiskInput:
    market_value = position.shares * close
    position_weight_equity = equity + (market_value * commission_rate)
    return RiskInput(
        position_weight=round(market_value / position_weight_equity, 6) if position_weight_equity > 0 else 0.0,
        portfolio_drawdown=round(max(0.0, (rolling_peak - equity) / rolling_peak), 6) if rolling_peak > 0 else 0.0,
        single_position_drawdown=(
            round(max(0.0, (position.cost_basis - close) / position.cost_basis), 6)
            if position.shares > 0 and position.cost_basis > 0
            else 0.0
        ),
    )


def _sell_position(
    *,
    trade_date: date,
    symbol: str,
    close: float,
    position: _Position,
    cash: float,
    commission_rate: float,
    slippage_rate: float,
    reason: str,
) -> tuple[PortfolioBacktestTrade, float, float, bool]:
    sell_price = round(close * (1.0 - slippage_rate), 6)
    notional = round(position.shares * sell_price, 6)
    commission = round(notional * commission_rate, 6)
    realized_pnl = round((sell_price - position.cost_basis) * position.shares - commission, 6)
    next_cash = cash + notional - commission
    trade = PortfolioBacktestTrade(
        trade_date=trade_date,
        symbol=symbol,
        action=TradeAction.SELL,
        price=sell_price,
        shares=position.shares,
        notional=notional,
        commission=commission,
        cash=round(next_cash, 6),
        position=0,
        reason=reason,
        realized_pnl=realized_pnl,
    )
    return trade, next_cash, notional, realized_pnl > 0


def _merge_risk_inputs(left: RiskInput, right: RiskInput) -> RiskInput:
    return RiskInput(
        position_weight=max(left.position_weight, right.position_weight),
        portfolio_drawdown=max(left.portfolio_drawdown, right.portfolio_drawdown),
        single_position_drawdown=max(left.single_position_drawdown, right.single_position_drawdown),
        st_warning=left.st_warning or right.st_warning,
        negative_event_count=max(left.negative_event_count, right.negative_event_count),
        goodwill_ratio=max(left.goodwill_ratio, right.goodwill_ratio),
        pledge_ratio=max(left.pledge_ratio, right.pledge_ratio),
        main_outflow_days=max(left.main_outflow_days, right.main_outflow_days),
        index_below_annual_ma=left.index_below_annual_ma or right.index_below_annual_ma,
        broad_market_drop_gt_3pct_count=max(
            left.broad_market_drop_gt_3pct_count,
            right.broad_market_drop_gt_3pct_count,
        ),
    )


def _round_lot(shares: int, lot_size: int) -> int:
    return (shares // lot_size) * lot_size


def _decision_weight(confidence: float) -> float:
    return min(1.0, max(0.0, float(confidence)))


def _bar_date(bar: Mapping[str, object]) -> date:
    raw_date = bar.get("trade_date")
    if isinstance(raw_date, date):
        return raw_date
    if isinstance(raw_date, str):
        return date.fromisoformat(raw_date)
    raise ValueError("bar is missing trade_date")


def _bar_close(bar: Mapping[str, object]) -> float:
    close = float(bar["close"])
    if close <= 0:
        raise ValueError("bar close must be positive")
    return close


def _dated_warnings(
    trade_date: date,
    symbol: str,
    risk_warnings: list[RiskWarning],
) -> list[PortfolioDatedRiskWarning]:
    return [
        PortfolioDatedRiskWarning(
            trade_date=trade_date,
            symbol=symbol,
            layer=warning.layer,
            rule=warning.rule,
            action=warning.action.value,
            message=warning.message,
            observed_value=warning.observed_value,
            threshold_value=warning.threshold_value,
        )
        for warning in risk_warnings
    ]
