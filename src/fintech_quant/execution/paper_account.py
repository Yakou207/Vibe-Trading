from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Mapping

from fintech_quant.backtesting.constraints import AShareTradingConstraints
from fintech_quant.backtesting.drawdown_control import (
    DrawdownControlPolicy,
    DrawdownControlState,
    DrawdownRegime,
    drawdown_control_state_from_json,
    drawdown_control_state_to_json,
    update_drawdown_control,
)


@dataclass(frozen=True)
class PaperPosition:
    shares: int
    cost_basis: float
    last_buy_date: date | None = None


@dataclass
class PaperAccount:
    cash: float
    positions: dict[str, PaperPosition] = field(default_factory=dict)
    nav_history: list[dict[str, object]] = field(default_factory=list)
    shadow_cash: float | None = None
    shadow_positions: dict[str, PaperPosition] = field(default_factory=dict)
    shadow_nav_history: list[dict[str, object]] = field(default_factory=list)
    drawdown_control_state: DrawdownControlState | None = None


@dataclass(frozen=True)
class PaperTradingResult:
    account: PaperAccount
    nav: dict[str, object]
    trades: list[dict[str, object]]
    blocked_orders: list[dict[str, object]]
    shadow_trades: list[dict[str, object]] = field(default_factory=list)


def run_paper_trading_day(
    account: PaperAccount,
    *,
    targets: Mapping[str, float],
    bars: Mapping[str, Mapping[str, object]],
    as_of: date,
    constraints: AShareTradingConstraints | None = None,
    commission_rate: float = 0.0003,
    slippage_rate: float = 0.0,
    drawdown_policy: DrawdownControlPolicy | None = None,
) -> PaperTradingResult:
    if drawdown_policy is not None:
        return _run_drawdown_controlled_day(
            account,
            targets=targets,
            bars=bars,
            as_of=as_of,
            constraints=constraints,
            commission_rate=commission_rate,
            slippage_rate=slippage_rate,
            policy=drawdown_policy,
        )
    active_constraints = constraints or AShareTradingConstraints()
    cash = float(account.cash)
    positions = dict(account.positions)
    trades: list[dict[str, object]] = []
    blocked: list[dict[str, object]] = []
    equity_before = _equity(cash, positions, bars)

    symbols = sorted(set(targets) | set(positions))
    for symbol in symbols:
        bar = bars.get(symbol)
        if bar is None:
            blocked.append({"symbol": symbol, "action": "rebalance", "reason": "missing_price"})
            continue
        close = _close(bar)
        current = positions.get(symbol, PaperPosition(shares=0, cost_basis=close))
        target_weight = max(0.0, float(targets.get(symbol, 0.0)))
        target_value = equity_before * target_weight
        current_value = current.shares * close
        value_diff = target_value - current_value
        if abs(value_diff) < close * active_constraints.lot_size:
            continue
        if value_diff > 0:
            order = _buy(
                symbol,
                close,
                value_diff,
                cash,
                bar,
                as_of,
                active_constraints,
                commission_rate,
                slippage_rate,
            )
            if order["blocked"]:
                blocked.append(order["blocked"])
                continue
            trade = order["trade"]
            cash = float(trade["cash"])
            previous_cost = current.cost_basis * current.shares
            new_shares = current.shares + int(trade["shares"])
            positions[symbol] = PaperPosition(
                shares=new_shares,
                cost_basis=round((previous_cost + float(trade["notional"])) / new_shares, 6),
                last_buy_date=as_of,
            )
            trades.append(trade)
            continue
        order = _sell(
            symbol,
            close,
            min(current.shares, _round_lot(int(abs(value_diff) // close), active_constraints.lot_size)),
            cash,
            current,
            bar,
            as_of,
            active_constraints,
            commission_rate,
            slippage_rate,
        )
        if order["blocked"]:
            blocked.append(order["blocked"])
            continue
        trade = order["trade"]
        cash = float(trade["cash"])
        remaining = current.shares - int(trade["shares"])
        if remaining > 0:
            positions[symbol] = PaperPosition(
                shares=remaining,
                cost_basis=current.cost_basis,
                last_buy_date=current.last_buy_date,
            )
        else:
            positions.pop(symbol, None)
        trades.append(trade)

    nav = _nav(as_of, cash, positions, bars)
    return PaperTradingResult(
        account=PaperAccount(
            cash=round(cash, 6),
            positions=positions,
            nav_history=[*account.nav_history, nav],
            shadow_cash=account.shadow_cash,
            shadow_positions=account.shadow_positions,
            shadow_nav_history=account.shadow_nav_history,
            drawdown_control_state=account.drawdown_control_state,
        ),
        nav=nav,
        trades=trades,
        blocked_orders=blocked,
    )


def _run_drawdown_controlled_day(
    account: PaperAccount,
    *,
    targets: Mapping[str, float],
    bars: Mapping[str, Mapping[str, object]],
    as_of: date,
    constraints: AShareTradingConstraints | None,
    commission_rate: float,
    slippage_rate: float,
    policy: DrawdownControlPolicy,
) -> PaperTradingResult:
    initial_equity = _equity(account.cash, account.positions, bars)
    state = account.drawdown_control_state or DrawdownControlState.initial(initial_equity)
    applied_regime = state.regime
    exposure_multiplier = {
        DrawdownRegime.NORMAL: 1.0,
        DrawdownRegime.REDUCED: 0.5,
        DrawdownRegime.LIQUIDATED: 0.0,
    }[applied_regime]
    actual_targets = {
        symbol: max(0.0, float(weight)) * exposure_multiplier
        for symbol, weight in targets.items()
    }
    actual_result = run_paper_trading_day(
        PaperAccount(
            cash=account.cash,
            positions=account.positions,
            nav_history=account.nav_history,
        ),
        targets=actual_targets,
        bars=bars,
        as_of=as_of,
        constraints=constraints,
        commission_rate=commission_rate,
        slippage_rate=slippage_rate,
    )
    shadow_is_initialized = account.shadow_cash is not None
    shadow_result = run_paper_trading_day(
        PaperAccount(
            cash=account.shadow_cash if shadow_is_initialized else account.cash,
            positions=(
                account.shadow_positions if shadow_is_initialized else account.positions
            ),
            nav_history=account.shadow_nav_history,
        ),
        targets=targets,
        bars=bars,
        as_of=as_of,
        constraints=constraints,
        commission_rate=commission_rate,
        slippage_rate=slippage_rate,
    )
    decision = update_drawdown_control(
        state,
        trade_date=as_of,
        actual_equity=float(actual_result.nav["equity"]),
        shadow_equity=float(shadow_result.nav["equity"]),
        policy=policy,
    )
    nav = {
        **actual_result.nav,
        "shadow_equity": shadow_result.nav["equity"],
        "applied_drawdown_regime": applied_regime.value,
        "next_drawdown_regime": decision.state.regime.value,
        "exposure_multiplier": exposure_multiplier,
    }
    return PaperTradingResult(
        account=PaperAccount(
            cash=actual_result.account.cash,
            positions=actual_result.account.positions,
            nav_history=[*account.nav_history, nav],
            shadow_cash=shadow_result.account.cash,
            shadow_positions=shadow_result.account.positions,
            shadow_nav_history=shadow_result.account.nav_history,
            drawdown_control_state=decision.state,
        ),
        nav=nav,
        trades=actual_result.trades,
        blocked_orders=actual_result.blocked_orders,
        shadow_trades=shadow_result.trades,
    )


def load_paper_account(path: Path, *, initial_cash: float) -> PaperAccount:
    if not path.exists():
        return PaperAccount(cash=initial_cash)
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_state = payload.get("drawdown_control_state")
    return PaperAccount(
        cash=float(payload["cash"]),
        positions=_positions_from_json(payload.get("positions", {})),
        nav_history=list(payload.get("nav_history", [])),
        shadow_cash=(
            float(payload["shadow_cash"]) if payload.get("shadow_cash") is not None else None
        ),
        shadow_positions=_positions_from_json(payload.get("shadow_positions", {})),
        shadow_nav_history=list(payload.get("shadow_nav_history", [])),
        drawdown_control_state=(
            drawdown_control_state_from_json(raw_state)
            if isinstance(raw_state, Mapping)
            else None
        ),
    )


def write_paper_account(path: Path, account: PaperAccount) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_account_to_json(account), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_paper_report(path: Path, result: PaperTradingResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "nav": result.nav,
                "trades": result.trades,
                "blocked_orders": result.blocked_orders,
                "shadow_trades": result.shadow_trades,
                "account": _account_to_json(result.account),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _buy(
    symbol: str,
    close: float,
    value_diff: float,
    cash: float,
    bar: Mapping[str, object],
    as_of: date,
    constraints: AShareTradingConstraints,
    commission_rate: float,
    slippage_rate: float,
) -> dict[str, object]:
    blocked = _blocked_buy(symbol, bar, constraints)
    if blocked:
        return {"blocked": blocked}
    price = round(close * (1.0 + slippage_rate), 6)
    shares = _round_lot(int(min(value_diff, cash) // price), constraints.lot_size)
    while shares > 0:
        notional = round(shares * price, 6)
        commission = round(notional * commission_rate, 6)
        if notional + commission <= cash:
            return {
                "trade": {
                    "trade_date": as_of.isoformat(),
                    "symbol": symbol,
                    "action": "buy",
                    "price": price,
                    "shares": shares,
                    "notional": notional,
                    "commission": commission,
                    "cash": round(cash - notional - commission, 6),
                },
                "blocked": None,
            }
        shares -= constraints.lot_size
    return {"blocked": {"symbol": symbol, "action": "buy", "reason": "insufficient_cash"}}


def _sell(
    symbol: str,
    close: float,
    shares: int,
    cash: float,
    position: PaperPosition,
    bar: Mapping[str, object],
    as_of: date,
    constraints: AShareTradingConstraints,
    commission_rate: float,
    slippage_rate: float,
) -> dict[str, object]:
    blocked = _blocked_sell(symbol, position, bar, as_of, constraints)
    if blocked:
        return {"blocked": blocked}
    shares = _round_lot(shares, constraints.lot_size)
    if shares <= 0:
        return {"blocked": {"symbol": symbol, "action": "sell", "reason": "below_lot_size"}}
    price = round(close * (1.0 - slippage_rate), 6)
    notional = round(shares * price, 6)
    commission = round(notional * commission_rate, 6)
    return {
        "trade": {
            "trade_date": as_of.isoformat(),
            "symbol": symbol,
            "action": "sell",
            "price": price,
            "shares": shares,
            "notional": notional,
            "commission": commission,
            "cash": round(cash + notional - commission, 6),
            "realized_pnl": round((price - position.cost_basis) * shares - commission, 6),
        },
        "blocked": None,
    }


def _blocked_buy(
    symbol: str,
    bar: Mapping[str, object],
    constraints: AShareTradingConstraints,
) -> dict[str, object] | None:
    if constraints.suspension_filter_required and _truthy(bar.get("is_suspended") or bar.get("suspended")):
        return {"symbol": symbol, "action": "buy", "reason": "suspended"}
    if constraints.price_limit_required and _truthy(bar.get("limit_up") or bar.get("is_limit_up")):
        return {"symbol": symbol, "action": "buy", "reason": "limit_up"}
    return None


def _blocked_sell(
    symbol: str,
    position: PaperPosition,
    bar: Mapping[str, object],
    as_of: date,
    constraints: AShareTradingConstraints,
) -> dict[str, object] | None:
    if constraints.t_plus_one and position.last_buy_date == as_of:
        return {"symbol": symbol, "action": "sell", "reason": "t_plus_one"}
    if constraints.suspension_filter_required and _truthy(bar.get("is_suspended") or bar.get("suspended")):
        return {"symbol": symbol, "action": "sell", "reason": "suspended"}
    if constraints.price_limit_required and _truthy(bar.get("limit_down") or bar.get("is_limit_down")):
        return {"symbol": symbol, "action": "sell", "reason": "limit_down"}
    return None


def _nav(
    as_of: date,
    cash: float,
    positions: Mapping[str, PaperPosition],
    bars: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    positions_value = sum(position.shares * _close(bars[symbol]) for symbol, position in positions.items() if symbol in bars)
    return {
        "trade_date": as_of.isoformat(),
        "cash": round(cash, 6),
        "positions_value": round(positions_value, 6),
        "equity": round(cash + positions_value, 6),
    }


def _equity(cash: float, positions: Mapping[str, PaperPosition], bars: Mapping[str, Mapping[str, object]]) -> float:
    return float(_nav(date.min, cash, positions, bars)["equity"])


def _account_to_json(account: PaperAccount) -> dict[str, object]:
    return {
        "cash": account.cash,
        "positions": _positions_to_json(account.positions),
        "nav_history": account.nav_history,
        "shadow_cash": account.shadow_cash,
        "shadow_positions": _positions_to_json(account.shadow_positions),
        "shadow_nav_history": account.shadow_nav_history,
        "drawdown_control_state": (
            drawdown_control_state_to_json(account.drawdown_control_state)
            if account.drawdown_control_state
            else None
        ),
    }


def _positions_to_json(
    positions: Mapping[str, PaperPosition],
) -> dict[str, dict[str, object]]:
    return {
        symbol: {
            "shares": position.shares,
            "cost_basis": position.cost_basis,
            "last_buy_date": (
                position.last_buy_date.isoformat() if position.last_buy_date else None
            ),
        }
        for symbol, position in sorted(positions.items())
    }


def _positions_from_json(payload: object) -> dict[str, PaperPosition]:
    if not isinstance(payload, Mapping):
        raise ValueError("paper positions must be an object")
    return {
        str(symbol): PaperPosition(
            shares=int(position["shares"]),
            cost_basis=float(position["cost_basis"]),
            last_buy_date=(
                date.fromisoformat(str(position["last_buy_date"]))
                if position.get("last_buy_date")
                else None
            ),
        )
        for symbol, position in payload.items()
        if isinstance(position, Mapping)
    }


def _round_lot(shares: int, lot_size: int) -> int:
    return (shares // lot_size) * lot_size


def _close(bar: Mapping[str, object]) -> float:
    close = float(bar["close"])
    if close <= 0:
        raise ValueError("close must be positive")
    return close


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}
