from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fintech_quant.execution.xtp import (
    XTP_MARKET_SH,
    XTP_MARKET_SZ,
    from_xtp_symbol,
    to_xtp_symbol,
)
from scripts.xtp_bridge import (
    _Collector,
    build_broker_state,
    submit_orders,
    verify_instructions,
)

TODAY = date(2026, 7, 28)


def test_symbol_mapping_round_trips_across_markets() -> None:
    assert to_xtp_symbol("600000.SH") == ("600000", XTP_MARKET_SH)
    assert to_xtp_symbol("000001.SZ") == ("000001", XTP_MARKET_SZ)
    assert to_xtp_symbol("300001") == ("300001", XTP_MARKET_SZ)  # exchange inferred

    assert from_xtp_symbol("600000", XTP_MARKET_SH) == "600000.SH"
    assert from_xtp_symbol("000001", XTP_MARKET_SZ) == "000001.SZ"


def test_from_xtp_symbol_rejects_unknown_market() -> None:
    with pytest.raises(ValueError, match="unsupported XTP market"):
        from_xtp_symbol("600000", 9)


def test_verify_instructions_rejects_non_simulation_mode() -> None:
    with pytest.raises(SystemExit, match="mode is 'live'"):
        verify_instructions({"mode": "live", "as_of": "2026-07-28"}, today=TODAY)


def test_verify_instructions_rejects_stale_date() -> None:
    with pytest.raises(SystemExit, match="dated 2026-07-27"):
        verify_instructions({"mode": "simulation", "as_of": "2026-07-27"}, today=TODAY)


def test_verify_instructions_accepts_today_and_explicit_stale_override() -> None:
    verify_instructions({"mode": "simulation", "as_of": "2026-07-28"}, today=TODAY)
    verify_instructions(
        {"mode": "simulation", "as_of": "2026-07-27"}, today=TODAY, allow_stale_date=True
    )


class _FakeApi:
    def __init__(self, order_ids: list[int]) -> None:
        self.requests: list[dict[str, object]] = []
        self._order_ids = list(order_ids)

    def insertOrder(self, request: dict[str, object], session_id: int) -> int:  # noqa: N802
        self.requests.append(dict(request))
        return self._order_ids.pop(0)


def test_submit_orders_maps_sides_markets_and_limit_prices() -> None:
    api = _FakeApi([111, 222])
    orders = [
        {"symbol": "600000.SH", "side": "buy", "shares": 700, "limit_price": 10.02},
        {"symbol": "000001.SZ", "side": "sell", "shares": 300, "limit_price": 9.98},
    ]

    submitted = submit_orders(api, 42, orders)

    buy, sell = api.requests
    assert (buy["ticker"], buy["market"], buy["side"], buy["quantity"]) == ("600000", 2, 1, 700)
    assert buy["price"] == 10.02
    assert buy["price_type"] == 1  # XTP_PRICE_LIMIT
    assert buy["business_type"] == 0  # XTP_BUSINESS_CASH
    assert (sell["ticker"], sell["market"], sell["side"], sell["quantity"]) == ("000001", 1, 2, 300)
    assert [row["order_xtp_id"] for row in submitted] == [111, 222]
    assert all(row["submitted"] for row in submitted)


def test_submit_orders_flags_rejected_submission() -> None:
    api = _FakeApi([0])

    submitted = submit_orders(api, 42, [{"symbol": "600000.SH", "side": "buy", "shares": 100, "limit_price": 10.0}])

    assert submitted[0]["submitted"] is False


def test_collector_counts_only_final_order_statuses() -> None:
    collector = _Collector()

    collector.on_order({"order_xtp_id": 1, "ticker": "600000", "order_status": 4}, None)  # queueing
    assert collector.final_order_count == 0

    collector.on_order({"order_xtp_id": 1, "ticker": "600000", "order_status": 1}, None)  # all traded
    collector.on_order({"order_xtp_id": 2, "ticker": "000001", "order_status": 6}, None)  # rejected
    assert collector.final_order_count == 2

    # A repeated terminal event for the same order must not double count.
    collector.on_order({"order_xtp_id": 2, "ticker": "000001", "order_status": 6}, None)
    assert collector.final_order_count == 2


def test_build_broker_state_matches_reconcile_schema() -> None:
    state = build_broker_state(
        as_of="2026-07-28",
        account_id="253191001825",
        asset={"buying_power": 92_950.0, "total_asset": 100_000.0},
        positions=[
            {"ticker": "600000", "market": 2, "total_qty": 700, "avg_price": 10.01},
            {"ticker": "000001", "market": 1, "total_qty": 0, "avg_price": 0.0},  # dropped
        ],
        fills=[
            {
                "ticker": "600000",
                "market": 2,
                "side": 1,
                "quantity": 700,
                "price": 10.01,
                "trade_time": "20260728093015000",
                "order_xtp_id": 111,
            }
        ],
        submitted_orders=[{"order_xtp_id": 111, "symbol": "600000.SH"}],
    )

    assert state["kind"] == "broker_state"
    assert state["mode"] == "simulation"
    assert state["cash"] == 92_950.0
    assert state["positions"] == [{"symbol": "600000.SH", "shares": 700, "avg_cost": 10.01}]
    assert state["fills"][0]["symbol"] == "600000.SH"
    assert state["fills"][0]["side"] == "buy"
    assert state["fills"][0]["shares"] == 700


def test_build_broker_state_reconciles_against_paper_account() -> None:
    from fintech_quant.execution.broker import reconcile_broker_state
    from fintech_quant.execution.paper_account import PaperAccount, PaperPosition

    state = build_broker_state(
        as_of="2026-07-28",
        account_id="253191001825",
        asset={"buying_power": 92_950.0, "total_asset": 100_000.0},
        positions=[{"ticker": "600000", "market": 2, "total_qty": 700, "avg_price": 10.01}],
        fills=[],
        submitted_orders=[],
    )
    account = PaperAccount(
        cash=92_930.0,
        positions={"600000.SH": PaperPosition(shares=700, cost_basis=10.0)},
    )

    report = reconcile_broker_state(account, state, cash_tolerance=100.0)

    assert report["status"] == "OK"
