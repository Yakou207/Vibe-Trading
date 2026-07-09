from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Mapping

from fintech_quant.backtesting.constraints import AShareTradingConstraints


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


@dataclass(frozen=True)
class PaperTradingResult:
    account: PaperAccount
    nav: dict[str, object]
    trades: list[dict[str, object]]
    blocked_orders: list[dict[str, object]]


def run_paper_trading_day(
    account: PaperAccount,
    *,
    targets: Mapping[str, float],
    bars: Mapping[str, Mapping[str, object]],
    as_of: date,
    constraints: AShareTradingConstraints | None = None,
    commission_rate: float = 0.0003,
    slippage_rate: float = 0.0,
) -> PaperTradingResult:
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
        account=PaperAccount(cash=round(cash, 6), positions=positions, nav_history=[*account.nav_history, nav]),
        nav=nav,
        trades=trades,
        blocked_orders=blocked,
    )


def load_paper_account(path: Path, *, initial_cash: float) -> PaperAccount:
    if not path.exists():
        return PaperAccount(cash=initial_cash)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return PaperAccount(
        cash=float(payload["cash"]),
        positions={
            symbol: PaperPosition(
                shares=int(position["shares"]),
                cost_basis=float(position["cost_basis"]),
                last_buy_date=(
                    date.fromisoformat(str(position["last_buy_date"]))
                    if position.get("last_buy_date")
                    else None
                ),
            )
            for symbol, position in payload.get("positions", {}).items()
        },
        nav_history=list(payload.get("nav_history", [])),
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
        "positions": {
            symbol: {
                "shares": position.shares,
                "cost_basis": position.cost_basis,
                "last_buy_date": position.last_buy_date.isoformat() if position.last_buy_date else None,
            }
            for symbol, position in sorted(account.positions.items())
        },
        "nav_history": account.nav_history,
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
