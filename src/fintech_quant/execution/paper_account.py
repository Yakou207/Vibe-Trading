from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Mapping

from fintech_quant.backtesting.constraints import AShareTradingConstraints
from fintech_quant.backtesting.costs import AShareCostModel
from fintech_quant.backtesting.drawdown_control import (
    DrawdownControlPolicy,
    DrawdownControlState,
    drawdown_exposure_multiplier,
    drawdown_control_state_from_json,
    drawdown_control_state_to_json,
    update_drawdown_control,
)
from fintech_quant.backtesting.corporate_actions import (
    AppliedCorporateAction,
    CorporateAction,
)
from fintech_quant.backtesting.dividend_tax import (
    DividendTaxLot,
    IndividualAShareDividendTaxPolicy,
    accrue_cash_dividend,
    apply_share_multiplier,
    settle_dividend_tax,
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
    dividend_tax_lots: dict[str, list[DividendTaxLot]] = field(default_factory=dict)
    shadow_dividend_tax_lots: dict[str, list[DividendTaxLot]] = field(default_factory=dict)
    pending_targets: dict[str, float] = field(default_factory=dict)
    pending_signal_date: date | None = None
    last_processed_date: date | None = None


@dataclass(frozen=True)
class PaperTradingResult:
    account: PaperAccount
    nav: dict[str, object]
    trades: list[dict[str, object]]
    blocked_orders: list[dict[str, object]]
    shadow_trades: list[dict[str, object]] = field(default_factory=list)
    corporate_actions: list[AppliedCorporateAction] = field(default_factory=list)


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
    corporate_actions: tuple[CorporateAction, ...] = (),
    dividend_tax_policy: IndividualAShareDividendTaxPolicy | None = None,
    cost_model: AShareCostModel | None = None,
    rights_issue_policy: str = "fail_closed",
) -> PaperTradingResult:
    if rights_issue_policy not in {"fail_closed", "do_not_subscribe"}:
        raise ValueError("unsupported rights_issue_policy")
    if account.last_processed_date is not None and as_of <= account.last_processed_date:
        raise ValueError("paper as_of must be after last processed date")
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
            corporate_actions=corporate_actions,
            dividend_tax_policy=dividend_tax_policy,
            cost_model=cost_model,
            rights_issue_policy=rights_issue_policy,
        )
    active_constraints = constraints or AShareTradingConstraints()
    active_cost_model = cost_model or AShareCostModel(
        commission_rate=commission_rate,
        minimum_commission=0.0,
        include_stamp_duty=False,
    )
    cash = float(account.cash)
    positions = dict(account.positions)
    dividend_tax_lots = _copy_dividend_tax_lots(account.dividend_tax_lots)
    applied_corporate_actions: list[AppliedCorporateAction] = []
    cash = _apply_corporate_actions(
        as_of,
        corporate_actions,
        positions,
        dividend_tax_lots,
        cash,
        applied_corporate_actions,
        rights_issue_policy,
    )
    trades: list[dict[str, object]] = []
    blocked: list[dict[str, object]] = []
    equity_before = _execution_equity(cash, positions, bars)

    symbols = sorted(set(targets) | set(positions))
    for symbol in symbols:
        bar = bars.get(symbol)
        if bar is None:
            blocked.append({"symbol": symbol, "action": "rebalance", "reason": "missing_price"})
            continue
        execution_price = _execution_price(bar)
        current = positions.get(
            symbol,
            PaperPosition(shares=0, cost_basis=execution_price),
        )
        target_weight = max(0.0, float(targets.get(symbol, 0.0)))
        target_value = equity_before * target_weight
        current_value = current.shares * execution_price
        value_diff = target_value - current_value
        if abs(value_diff) < execution_price * active_constraints.lot_size:
            continue
        if value_diff > 0:
            order = _buy(
                symbol,
                execution_price,
                value_diff,
                cash,
                bar,
                as_of,
                active_constraints,
                active_cost_model,
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
            if dividend_tax_policy is not None:
                dividend_tax_lots.setdefault(symbol, []).append(
                    DividendTaxLot(shares=int(trade["shares"]), acquired_date=as_of)
                )
            trades.append(trade)
            continue
        order = _sell(
            symbol,
            execution_price,
            min(
                current.shares,
                _round_lot(
                    int(abs(value_diff) // execution_price),
                    active_constraints.lot_size,
                ),
            ),
            cash,
            current,
            bar,
            as_of,
            active_constraints,
            active_cost_model,
            slippage_rate,
            dividend_tax_lots.get(symbol),
            dividend_tax_policy,
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
            dividend_tax_lots=dividend_tax_lots,
            shadow_dividend_tax_lots=account.shadow_dividend_tax_lots,
            pending_targets=dict(account.pending_targets),
            pending_signal_date=account.pending_signal_date,
            last_processed_date=as_of,
        ),
        nav=nav,
        trades=trades,
        blocked_orders=blocked,
        corporate_actions=applied_corporate_actions,
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
    corporate_actions: tuple[CorporateAction, ...],
    dividend_tax_policy: IndividualAShareDividendTaxPolicy | None,
    cost_model: AShareCostModel | None,
    rights_issue_policy: str,
) -> PaperTradingResult:
    initial_equity = _equity(account.cash, account.positions, bars)
    state = account.drawdown_control_state or DrawdownControlState.initial(initial_equity)
    applied_regime = state.regime
    exposure_multiplier = drawdown_exposure_multiplier(applied_regime)
    actual_targets = {
        symbol: max(0.0, float(weight)) * exposure_multiplier for symbol, weight in targets.items()
    }
    actual_result = run_paper_trading_day(
        PaperAccount(
            cash=account.cash,
            positions=account.positions,
            nav_history=account.nav_history,
            dividend_tax_lots=_copy_dividend_tax_lots(account.dividend_tax_lots),
            last_processed_date=account.last_processed_date,
        ),
        targets=actual_targets,
        bars=bars,
        as_of=as_of,
        constraints=constraints,
        commission_rate=commission_rate,
        slippage_rate=slippage_rate,
        corporate_actions=corporate_actions,
        dividend_tax_policy=dividend_tax_policy,
        cost_model=cost_model,
        rights_issue_policy=rights_issue_policy,
    )
    shadow_is_initialized = account.shadow_cash is not None
    shadow_result = run_paper_trading_day(
        PaperAccount(
            cash=account.shadow_cash if shadow_is_initialized else account.cash,
            positions=(account.shadow_positions if shadow_is_initialized else account.positions),
            nav_history=account.shadow_nav_history,
            dividend_tax_lots=_copy_dividend_tax_lots(
                account.shadow_dividend_tax_lots
                if shadow_is_initialized
                else account.dividend_tax_lots
            ),
            last_processed_date=account.last_processed_date,
        ),
        targets=targets,
        bars=bars,
        as_of=as_of,
        constraints=constraints,
        commission_rate=commission_rate,
        slippage_rate=slippage_rate,
        corporate_actions=corporate_actions,
        dividend_tax_policy=dividend_tax_policy,
        cost_model=cost_model,
        rights_issue_policy=rights_issue_policy,
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
            dividend_tax_lots=actual_result.account.dividend_tax_lots,
            shadow_dividend_tax_lots=shadow_result.account.dividend_tax_lots,
            pending_targets=dict(account.pending_targets),
            pending_signal_date=account.pending_signal_date,
            last_processed_date=as_of,
        ),
        nav=nav,
        trades=actual_result.trades,
        blocked_orders=actual_result.blocked_orders,
        shadow_trades=shadow_result.trades,
        corporate_actions=actual_result.corporate_actions,
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
            drawdown_control_state_from_json(raw_state) if isinstance(raw_state, Mapping) else None
        ),
        dividend_tax_lots=_dividend_tax_lots_from_json(payload.get("dividend_tax_lots", {})),
        shadow_dividend_tax_lots=_dividend_tax_lots_from_json(
            payload.get("shadow_dividend_tax_lots", {})
        ),
        pending_targets={
            str(symbol): float(weight)
            for symbol, weight in payload.get("pending_targets", {}).items()
        }
        if isinstance(payload.get("pending_targets", {}), Mapping)
        else {},
        pending_signal_date=(
            date.fromisoformat(str(payload["pending_signal_date"]))
            if payload.get("pending_signal_date")
            else None
        ),
        last_processed_date=(
            date.fromisoformat(str(payload["last_processed_date"]))
            if payload.get("last_processed_date")
            else None
        ),
    )


def write_paper_account(path: Path, account: PaperAccount) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_account_to_json(account), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_paper_report(path: Path, result: PaperTradingResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "nav": result.nav,
                "trades": result.trades,
                "blocked_orders": result.blocked_orders,
                "shadow_trades": result.shadow_trades,
                "corporate_actions": [
                    {
                        "symbol": action.symbol,
                        "ex_date": action.ex_date.isoformat(),
                        "cash_dividend_per_share": action.cash_dividend_per_share,
                        "share_multiplier": action.share_multiplier,
                        "shares_before": action.shares_before,
                        "shares_after": action.shares_after,
                        "cash_delta": action.cash_delta,
                        "source": action.source,
                        "action_type": action.action_type,
                        "rights_ratio": action.rights_ratio,
                        "rights_price": action.rights_price,
                        "rights_issue_policy": action.rights_issue_policy,
                    }
                    for action in result.corporate_actions
                ],
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
    cost_model: AShareCostModel,
    slippage_rate: float,
) -> dict[str, object]:
    blocked = _blocked_buy(symbol, bar, constraints)
    if blocked:
        return {"blocked": blocked}
    price = round(close * (1.0 + slippage_rate), 6)
    shares = _round_lot(int(min(value_diff, cash) // price), constraints.lot_size)
    while shares > 0:
        notional = round(shares * price, 6)
        cost = cost_model.buy_cost(notional, as_of)
        if notional + cost.total <= cash:
            return {
                "trade": {
                    "trade_date": as_of.isoformat(),
                    "symbol": symbol,
                    "action": "buy",
                    "price": price,
                    "shares": shares,
                    "notional": notional,
                    "commission": cost.commission,
                    "stamp_duty": cost.stamp_duty,
                    "total_cost": cost.total,
                    "cash": round(cash - notional - cost.total, 6),
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
    cost_model: AShareCostModel,
    slippage_rate: float,
    dividend_tax_lots: list[DividendTaxLot] | None,
    dividend_tax_policy: IndividualAShareDividendTaxPolicy | None,
) -> dict[str, object]:
    blocked = _blocked_sell(symbol, position, bar, as_of, constraints)
    if blocked:
        return {"blocked": blocked}
    shares = _round_lot(shares, constraints.lot_size)
    if shares <= 0:
        return {"blocked": {"symbol": symbol, "action": "sell", "reason": "below_lot_size"}}
    price = round(close * (1.0 - slippage_rate), 6)
    notional = round(shares * price, 6)
    cost = cost_model.sell_cost(notional, as_of)
    dividend_tax = 0.0
    if dividend_tax_policy is not None:
        if dividend_tax_lots is None:
            raise ValueError("dividend-tax policy requires paper acquisition lots")
        dividend_tax = settle_dividend_tax(
            dividend_tax_lots,
            shares_sold=shares,
            sale_date=as_of,
            policy=dividend_tax_policy,
        )
    return {
        "trade": {
            "trade_date": as_of.isoformat(),
            "symbol": symbol,
            "action": "sell",
            "price": price,
            "shares": shares,
            "notional": notional,
            "commission": cost.commission,
            "stamp_duty": cost.stamp_duty,
            "dividend_tax": dividend_tax,
            "total_cost": round(cost.total + dividend_tax, 6),
            "cash": round(cash + notional - cost.total - dividend_tax, 6),
            "realized_pnl": round(
                (price - position.cost_basis) * shares - cost.total - dividend_tax,
                6,
            ),
        },
        "blocked": None,
    }


def _blocked_buy(
    symbol: str,
    bar: Mapping[str, object],
    constraints: AShareTradingConstraints,
) -> dict[str, object] | None:
    if constraints.suspension_filter_required and _truthy(
        bar.get("is_suspended") or bar.get("suspended")
    ):
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
    if constraints.suspension_filter_required and _truthy(
        bar.get("is_suspended") or bar.get("suspended")
    ):
        return {"symbol": symbol, "action": "sell", "reason": "suspended"}
    if constraints.price_limit_required and _truthy(
        bar.get("limit_down") or bar.get("is_limit_down")
    ):
        return {"symbol": symbol, "action": "sell", "reason": "limit_down"}
    return None


def _nav(
    as_of: date,
    cash: float,
    positions: Mapping[str, PaperPosition],
    bars: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    positions_value = sum(
        position.shares * _close(bars[symbol])
        for symbol, position in positions.items()
        if symbol in bars
    )
    return {
        "trade_date": as_of.isoformat(),
        "cash": round(cash, 6),
        "positions_value": round(positions_value, 6),
        "equity": round(cash + positions_value, 6),
    }


def _equity(
    cash: float, positions: Mapping[str, PaperPosition], bars: Mapping[str, Mapping[str, object]]
) -> float:
    return float(_nav(date.min, cash, positions, bars)["equity"])


def _execution_equity(
    cash: float,
    positions: Mapping[str, PaperPosition],
    bars: Mapping[str, Mapping[str, object]],
) -> float:
    return cash + sum(
        position.shares * _execution_price(bars[symbol])
        for symbol, position in positions.items()
        if symbol in bars
    )


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
        "dividend_tax_lots": _dividend_tax_lots_to_json(account.dividend_tax_lots),
        "shadow_dividend_tax_lots": _dividend_tax_lots_to_json(account.shadow_dividend_tax_lots),
        "pending_targets": dict(sorted(account.pending_targets.items())),
        "pending_signal_date": (
            account.pending_signal_date.isoformat() if account.pending_signal_date else None
        ),
        "last_processed_date": (
            account.last_processed_date.isoformat() if account.last_processed_date else None
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


def _copy_dividend_tax_lots(
    lots_by_symbol: Mapping[str, list[DividendTaxLot]],
) -> dict[str, list[DividendTaxLot]]:
    return {
        symbol: [
            DividendTaxLot(
                shares=lot.shares,
                acquired_date=lot.acquired_date,
                pending_dividend=lot.pending_dividend,
            )
            for lot in lots
        ]
        for symbol, lots in lots_by_symbol.items()
    }


def _dividend_tax_lots_to_json(
    lots_by_symbol: Mapping[str, list[DividendTaxLot]],
) -> dict[str, list[dict[str, object]]]:
    return {
        symbol: [
            {
                "shares": lot.shares,
                "acquired_date": lot.acquired_date.isoformat(),
                "pending_dividend": lot.pending_dividend,
            }
            for lot in lots
        ]
        for symbol, lots in sorted(lots_by_symbol.items())
    }


def _dividend_tax_lots_from_json(
    payload: object,
) -> dict[str, list[DividendTaxLot]]:
    if not isinstance(payload, Mapping):
        raise ValueError("paper dividend-tax lots must be an object")
    result: dict[str, list[DividendTaxLot]] = {}
    for symbol, raw_lots in payload.items():
        if not isinstance(raw_lots, list):
            raise ValueError("paper dividend-tax symbol lots must be a list")
        result[str(symbol)] = [
            DividendTaxLot(
                shares=int(item["shares"]),
                acquired_date=date.fromisoformat(str(item["acquired_date"])),
                pending_dividend=float(item.get("pending_dividend", 0.0)),
            )
            for item in raw_lots
            if isinstance(item, Mapping)
        ]
    return result


def _apply_corporate_actions(
    as_of: date,
    actions: tuple[CorporateAction, ...],
    positions: dict[str, PaperPosition],
    dividend_tax_lots: dict[str, list[DividendTaxLot]],
    cash: float,
    applied: list[AppliedCorporateAction],
    rights_issue_policy: str,
) -> float:
    for action in actions:
        if action.ex_date != as_of:
            raise ValueError("paper corporate actions must match the trading date")
        position = positions.get(action.symbol)
        if position is None or position.shares <= 0:
            continue
        shares_before = position.shares
        if action.action_type == "rights_issue":
            if rights_issue_policy == "fail_closed":
                raise ValueError(
                    f"rights issue requires explicit policy for {action.symbol} "
                    f"on {as_of.isoformat()}"
                )
            applied.append(
                AppliedCorporateAction(
                    symbol=action.symbol,
                    ex_date=as_of,
                    cash_dividend_per_share=0.0,
                    share_multiplier=1.0,
                    shares_before=shares_before,
                    shares_after=shares_before,
                    cash_delta=0.0,
                    source=action.source,
                    action_type=action.action_type,
                    rights_ratio=action.rights_ratio,
                    rights_price=action.rights_price,
                    rights_issue_policy=rights_issue_policy,
                )
            )
            continue
        raw_shares_after = shares_before * action.share_multiplier
        shares_after = round(raw_shares_after)
        if abs(raw_shares_after - shares_after) > 1e-6:
            raise ValueError("paper corporate action creates fractional shares")
        cash_delta = round(shares_before * action.cash_dividend_per_share, 6)
        cash += cash_delta
        lots = dividend_tax_lots.get(action.symbol, [])
        accrue_cash_dividend(
            lots,
            cash_dividend_per_share=action.cash_dividend_per_share,
        )
        apply_share_multiplier(lots, share_multiplier=action.share_multiplier)
        positions[action.symbol] = PaperPosition(
            shares=shares_after,
            cost_basis=position.cost_basis / action.share_multiplier,
            last_buy_date=position.last_buy_date,
        )
        applied.append(
            AppliedCorporateAction(
                symbol=action.symbol,
                ex_date=as_of,
                cash_dividend_per_share=action.cash_dividend_per_share,
                share_multiplier=action.share_multiplier,
                shares_before=shares_before,
                shares_after=shares_after,
                cash_delta=cash_delta,
                source=action.source,
                action_type=action.action_type,
            )
        )
    return cash


def _round_lot(shares: int, lot_size: int) -> int:
    return (shares // lot_size) * lot_size


def _close(bar: Mapping[str, object]) -> float:
    close = float(bar["close"])
    if close <= 0:
        raise ValueError("close must be positive")
    return close


def _execution_price(bar: Mapping[str, object]) -> float:
    price = float(bar.get("execution_price", bar.get("open", bar["close"])))
    if price <= 0:
        raise ValueError("execution price must be positive")
    return price


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}
