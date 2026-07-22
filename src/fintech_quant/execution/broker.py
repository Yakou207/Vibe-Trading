from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping

from fintech_quant.backtesting.constraints import AShareTradingConstraints
from fintech_quant.backtesting.costs import AShareCostModel
from fintech_quant.data.run_artifacts import sha256_file
from fintech_quant.execution.paper_account import PaperAccount

ORDER_INSTRUCTIONS_SCHEMA_VERSION = 1
ORDER_INSTRUCTIONS_KIND = "live_order_instructions"
BROKER_STATE_KIND = "broker_state"
SIMULATION_MODE = "simulation"


@dataclass(frozen=True)
class OrderInstruction:
    symbol: str
    side: str
    shares: int
    limit_price: float
    reference_price: float
    target_weight: float


def build_order_instructions(
    account: PaperAccount,
    *,
    targets: Mapping[str, float],
    quotes: Mapping[str, float],
    as_of: date,
    constraints: AShareTradingConstraints | None = None,
    cost_model: AShareCostModel | None = None,
    limit_offset: float = 0.002,
) -> tuple[list[OrderInstruction], list[dict[str, object]]]:
    """Translate queued target weights into lot-sized limit orders.

    Sizing mirrors ``run_paper_trading_day``: the value difference against
    current equity decides direction, one lot is the minimum trade, buys are
    downsized to projected cash, and same-day buys cannot be sold (T+1).
    """
    active_constraints = constraints or AShareTradingConstraints()
    active_cost_model = cost_model or AShareCostModel()
    lot = active_constraints.lot_size

    equity = float(account.cash)
    for symbol, position in account.positions.items():
        price = quotes.get(symbol)
        if price is not None:
            equity += position.shares * float(price)

    cash = float(account.cash)
    orders: list[OrderInstruction] = []
    skipped: list[dict[str, object]] = []
    for symbol in sorted(set(targets) | set(account.positions)):
        price = quotes.get(symbol)
        if price is None or float(price) <= 0:
            skipped.append({"symbol": symbol, "reason": "missing_quote"})
            continue
        price = float(price)
        position = account.positions.get(symbol)
        held_shares = position.shares if position is not None else 0
        target_weight = max(0.0, float(targets.get(symbol, 0.0)))
        value_diff = equity * target_weight - held_shares * price
        if abs(value_diff) < price * lot:
            skipped.append({"symbol": symbol, "reason": "below_one_lot"})
            continue
        if value_diff > 0:
            limit_price = round(price * (1.0 + limit_offset), 2)
            shares = _round_lot(int(min(value_diff, cash) // limit_price), lot)
            while shares > 0:
                notional = shares * limit_price
                cost = active_cost_model.buy_cost(notional, as_of)
                if notional + cost.total <= cash:
                    break
                shares -= lot
            if shares <= 0:
                skipped.append({"symbol": symbol, "reason": "insufficient_cash"})
                continue
            cash -= shares * limit_price + active_cost_model.buy_cost(shares * limit_price, as_of).total
            orders.append(
                OrderInstruction(
                    symbol=symbol,
                    side="buy",
                    shares=shares,
                    limit_price=limit_price,
                    reference_price=price,
                    target_weight=target_weight,
                )
            )
            continue
        if position is None or held_shares <= 0:
            skipped.append({"symbol": symbol, "reason": "no_sellable_shares"})
            continue
        if active_constraints.t_plus_one and position.last_buy_date == as_of:
            skipped.append({"symbol": symbol, "reason": "t_plus_one_locked"})
            continue
        shares = min(held_shares, _round_lot(int(abs(value_diff) // price), lot))
        if shares <= 0:
            skipped.append({"symbol": symbol, "reason": "below_one_lot"})
            continue
        limit_price = round(price * (1.0 - limit_offset), 2)
        notional = shares * limit_price
        cash += notional - active_cost_model.sell_cost(notional, as_of).total
        orders.append(
            OrderInstruction(
                symbol=symbol,
                side="sell",
                shares=shares,
                limit_price=limit_price,
                reference_price=price,
                target_weight=target_weight,
            )
        )
    return orders, skipped


def write_order_instructions(
    path: Path,
    *,
    orders: list[OrderInstruction],
    skipped: list[dict[str, object]],
    as_of: date,
    mode: str,
    source_paths: Mapping[str, Path],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": ORDER_INSTRUCTIONS_SCHEMA_VERSION,
        "kind": ORDER_INSTRUCTIONS_KIND,
        "as_of": as_of.isoformat(),
        "mode": mode,
        "source": {
            name: {"path": str(source), "sha256": sha256_file(source)}
            for name, source in sorted(source_paths.items())
        },
        "orders": [
            {
                "symbol": order.symbol,
                "side": order.side,
                "shares": order.shares,
                "limit_price": order.limit_price,
                "reference_price": order.reference_price,
                "target_weight": order.target_weight,
            }
            for order in orders
        ],
        "skipped": skipped,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def load_order_instructions(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    if payload.get("schema_version") != ORDER_INSTRUCTIONS_SCHEMA_VERSION:
        raise ValueError(f"unsupported order-instruction schema: {payload.get('schema_version')!r}")
    if payload.get("kind") != ORDER_INSTRUCTIONS_KIND:
        raise ValueError(f"unsupported order-instruction kind: {payload.get('kind')!r}")
    return payload


def reconcile_broker_state(
    account: PaperAccount,
    broker_state: Mapping[str, object],
    *,
    cash_tolerance: float = 100.0,
) -> dict[str, object]:
    """Compare a broker account export against the canonical paper account.

    Share counts must match exactly; cash must match within ``cash_tolerance``
    CNY (fill prices legitimately differ from the paper open-price model).
    """
    if broker_state.get("kind") != BROKER_STATE_KIND:
        raise ValueError(f"unsupported broker-state kind: {broker_state.get('kind')!r}")
    differences: list[dict[str, object]] = []

    broker_cash = float(broker_state.get("cash", 0.0))
    cash_gap = broker_cash - float(account.cash)
    if abs(cash_gap) > cash_tolerance:
        differences.append(
            {
                "field": "cash",
                "paper": float(account.cash),
                "broker": broker_cash,
                "gap": round(cash_gap, 6),
            }
        )

    broker_positions: dict[str, int] = {}
    for row in broker_state.get("positions", []):
        if not isinstance(row, Mapping):
            raise ValueError("broker-state positions must be objects")
        broker_positions[str(row["symbol"])] = int(row["shares"])
    for symbol in sorted(set(broker_positions) | set(account.positions)):
        paper_shares = account.positions[symbol].shares if symbol in account.positions else 0
        broker_shares = broker_positions.get(symbol, 0)
        if paper_shares != broker_shares:
            differences.append(
                {
                    "field": "position",
                    "symbol": symbol,
                    "paper": paper_shares,
                    "broker": broker_shares,
                }
            )

    return {
        "status": "OK" if not differences else "FAILED",
        "as_of": str(broker_state.get("as_of", "")),
        "cash_tolerance": cash_tolerance,
        "differences": differences,
    }


def _round_lot(shares: int, lot_size: int) -> int:
    return (shares // lot_size) * lot_size
