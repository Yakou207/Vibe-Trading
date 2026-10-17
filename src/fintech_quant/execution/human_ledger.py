"""Human execution ledger: what a person actually traded after a pre-market brief.

This ledger is deliberately separate from the paper account. Nothing in the V2
paper-evidence chain reads it, and the functions here only read paper artifacts.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

from fintech_quant.data.symbols import normalize_a_share_symbol

LEDGER_FIELDS = (
    "trade_date",
    "signal_date",
    "symbol",
    "action",
    "shares",
    "fill_price",
    "fees",
    "skip_reason",
    "note",
)
ACTIONS = ("buy", "sell", "skip")
LOT_SIZE = 100


class LedgerError(ValueError):
    pass


def validate_entry(
    row: Mapping[str, object],
    brief: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return a normalized ledger row or raise ``LedgerError``."""
    try:
        trade_date = date.fromisoformat(str(row.get("trade_date", "")).strip())
        signal_date = date.fromisoformat(str(row.get("signal_date", "")).strip())
    except ValueError as exc:
        raise LedgerError(f"invalid ISO date: {exc}") from exc
    if trade_date <= signal_date:
        raise LedgerError("trade_date must be after signal_date (targets execute next session)")
    try:
        symbol = normalize_a_share_symbol(str(row.get("symbol", "")))
    except ValueError as exc:
        raise LedgerError(str(exc)) from exc
    action = str(row.get("action", "")).strip().lower()
    if action not in ACTIONS:
        raise LedgerError(f"action must be one of {ACTIONS}")
    skip_reason = str(row.get("skip_reason") or "").strip()
    note = str(row.get("note") or "").strip()
    normalized: dict[str, object] = {
        "trade_date": trade_date.isoformat(),
        "signal_date": signal_date.isoformat(),
        "symbol": symbol,
        "action": action,
        "shares": "",
        "fill_price": "",
        "fees": "",
        "skip_reason": skip_reason,
        "note": note,
    }
    if action == "skip":
        if not skip_reason:
            raise LedgerError("skip rows require skip_reason")
        if not _blank(row.get("shares")) or not _blank(row.get("fill_price")):
            raise LedgerError("skip rows must not carry shares or fill_price")
    else:
        if skip_reason:
            raise LedgerError("only skip rows may carry skip_reason")
        shares = _positive_int(row.get("shares"), "shares")
        if action == "buy" and shares % LOT_SIZE:
            raise LedgerError(f"buy shares must be a multiple of {LOT_SIZE}")
        if action == "buy" and symbol.startswith(("688", "689")) and shares < 200:
            raise LedgerError("STAR Market buys require at least 200 shares")
        price = _positive_float(row.get("fill_price"), "fill_price")
        fees = 0.0 if _blank(row.get("fees")) else _non_negative_float(row.get("fees"), "fees")
        normalized.update(shares=shares, fill_price=price, fees=fees)

    if brief is not None and brief.get("signal_date") == normalized["signal_date"]:
        items = {
            str(item["symbol"]): item
            for key in ("targets", "near_miss", "paper_exits")
            for item in brief[key]
        }
        item = items.get(symbol)
        if action == "skip" and (item is None or item["category"] == "near_miss"):
            raise LedgerError("skip rows must name a brief target or paper exit")
        if action != "skip" and item and item.get("limit_up") is not None:
            price = float(normalized["fill_price"])
            if not float(item["limit_down"]) <= price <= float(item["limit_up"]):
                raise LedgerError(
                    f"fill_price {price} is outside the limit band "
                    f"[{item['limit_down']}, {item['limit_up']}]"
                )
    return normalized


def load_ledger(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != LEDGER_FIELDS:
            raise LedgerError(f"{path} header must be {','.join(LEDGER_FIELDS)}")
        rows = []
        for line, row in enumerate(reader, start=2):
            try:
                rows.append(validate_entry(row))
            except LedgerError as exc:
                raise LedgerError(f"{path}:{line}: {exc}") from exc
    return rows


def append_entry(path: Path, row: Mapping[str, object], brief: Mapping[str, object] | None) -> dict:
    """Validate and append one row; existing rows are never rewritten."""
    load_ledger(path)
    normalized = validate_entry(row, brief)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=LEDGER_FIELDS, lineterminator="\n")
    new_file = not path.exists()
    if new_file:
        writer.writeheader()
    writer.writerow(normalized)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x" if new_file else "a", encoding="utf-8", newline="") as handle:
        handle.write(buffer.getvalue())
    return normalized


def compare_to_paper(
    ledger: Sequence[Mapping[str, object]],
    brief: Mapping[str, object],
    paper_trades: Sequence[Mapping[str, object]] | None,
) -> dict[str, object]:
    """Implementation shortfall and skip rate of human fills versus the paper account.

    Shortfall is signed so that positive basis points are a cost: buys above the
    decision price (previous close) or sells below it.
    """
    signal_date = str(brief["signal_date"])
    rows = [row for row in ledger if row["signal_date"] == signal_date]
    planned = {
        str(item["symbol"]): ("buy" if item["category"] == "target" else "sell", item)
        for key in ("targets", "paper_exits")
        for item in brief[key]
    }
    paper_by_symbol: dict[str, list[Mapping[str, object]]] = {}
    for trade in paper_trades or []:
        paper_by_symbol.setdefault(str(trade["symbol"]), []).append(trade)

    lines = []
    for symbol, (side, item) in sorted(planned.items()):
        decision_price = item.get("previous_close")
        mine = [row for row in rows if row["symbol"] == symbol]
        skips = [row for row in mine if row["action"] == "skip"]
        fills = [row for row in mine if row["action"] == side]
        human = _fill_summary(fills, side, decision_price)
        paper = _fill_summary(
            [
                {"shares": t["shares"], "fill_price": t["price"], "fees": t.get("total_cost", 0.0)}
                for t in paper_by_symbol.get(symbol, [])
                if t["action"] == side
            ],
            side,
            decision_price,
        )
        status = "filled" if fills else "skipped" if skips else "unrecorded"
        line: dict[str, object] = {
            "symbol": symbol,
            "side": side,
            "status": status,
            "skip_reasons": [row["skip_reason"] for row in skips],
            "decision_price": decision_price,
            "planned_shares": (item.get("suggested") or {}).get("shares"),
            "human": human,
            "paper": paper if paper_trades is not None else None,
            "human_vs_paper_bps": None,
        }
        if human and paper and paper_trades is not None:
            sign = 1.0 if side == "buy" else -1.0
            line["human_vs_paper_bps"] = round(
                sign * (human["vwap"] / paper["vwap"] - 1.0) * 1e4, 2
            )
        lines.append(line)

    off_brief = [
        row
        for row in rows
        if row["action"] != "skip"
        and (row["symbol"] not in planned or planned[row["symbol"]][0] != row["action"])
    ]
    planned_count = len(lines)
    skipped = sum(1 for line in lines if line["status"] == "skipped")
    unrecorded = sum(1 for line in lines if line["status"] == "unrecorded")
    human_cost = sum(line["human"]["shortfall_cny"] for line in lines if line["human"])
    human_notional = sum(line["human"]["decision_notional"] for line in lines if line["human"])
    paper_lines = [line for line in lines if line["paper"]]
    paper_cost = sum(line["paper"]["shortfall_cny"] for line in paper_lines)
    paper_notional = sum(line["paper"]["decision_notional"] for line in paper_lines)
    return {
        "kind": "human_execution_comparison",
        "signal_date": signal_date,
        "counts_toward_paper_evidence": False,
        "paper_execution_available": paper_trades is not None,
        "summary": {
            "planned_orders": planned_count,
            "filled": sum(1 for line in lines if line["status"] == "filled"),
            "skipped": skipped,
            "unrecorded": unrecorded,
            "skip_rate": round(skipped / planned_count, 6) if planned_count else None,
            "unrecorded_rate": round(unrecorded / planned_count, 6) if planned_count else None,
            "human_shortfall_cny": round(human_cost, 2),
            "human_shortfall_bps": _bps(human_cost, human_notional),
            "paper_shortfall_cny": round(paper_cost, 2) if paper_trades is not None else None,
            "paper_shortfall_bps": _bps(paper_cost, paper_notional)
            if paper_trades is not None
            else None,
            "off_brief_trades": len(off_brief),
        },
        "orders": lines,
        "off_brief_trades": off_brief,
    }


def _fill_summary(
    fills: Sequence[Mapping[str, object]], side: str, decision_price: object
) -> dict[str, float] | None:
    shares = sum(int(f["shares"]) for f in fills)
    if not shares or decision_price is None:
        return None
    notional = sum(int(f["shares"]) * float(f["fill_price"]) for f in fills)
    fees = sum(float(f.get("fees") or 0.0) for f in fills)
    vwap = notional / shares
    decision_notional = shares * float(decision_price)
    sign = 1.0 if side == "buy" else -1.0
    shortfall = sign * (notional - decision_notional) + fees
    return {
        "shares": shares,
        "vwap": round(vwap, 6),
        "fees": round(fees, 2),
        "decision_notional": round(decision_notional, 2),
        "shortfall_cny": round(shortfall, 2),
        "shortfall_bps": _bps(shortfall, decision_notional),
    }


def _bps(cost: float, notional: float) -> float | None:
    return round(cost / notional * 1e4, 2) if notional else None


def _blank(value: object) -> bool:
    return value is None or str(value).strip() == ""


def _positive_int(value: object, name: str) -> int:
    try:
        number = float(str(value).strip())
    except ValueError as exc:
        raise LedgerError(f"{name} must be a positive integer") from exc
    if not number.is_integer() or number <= 0:
        raise LedgerError(f"{name} must be a positive integer")
    return int(number)


def _positive_float(value: object, name: str) -> float:
    number = _non_negative_float(value, name)
    if number == 0:
        raise LedgerError(f"{name} must be positive")
    return number


def _non_negative_float(value: object, name: str) -> float:
    try:
        number = float(str(value).strip())
    except ValueError as exc:
        raise LedgerError(f"{name} must be numeric") from exc
    if not math.isfinite(number) or number < 0:
        raise LedgerError(f"{name} must be a non-negative finite number")
    return number
