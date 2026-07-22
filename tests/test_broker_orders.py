from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from fintech_quant.execution.broker import (
    build_order_instructions,
    load_order_instructions,
    reconcile_broker_state,
    write_order_instructions,
)
from fintech_quant.execution.paper_account import PaperAccount, PaperPosition

AS_OF = date(2026, 7, 22)


def test_build_orders_sizes_buys_in_lots_from_target_weights() -> None:
    account = PaperAccount(cash=100_000.0)

    orders, skipped = build_order_instructions(
        account,
        targets={"600000.SH": 0.08},
        quotes={"600000.SH": 10.0},
        as_of=AS_OF,
    )

    assert skipped == []
    assert len(orders) == 1
    order = orders[0]
    assert order.side == "buy"
    assert order.shares == 700  # 8000 CNY at limit 10.02 -> 798 shares -> 7 lots
    assert order.limit_price == 10.02
    assert order.reference_price == 10.0


def test_build_orders_skips_below_one_lot_and_missing_quotes() -> None:
    account = PaperAccount(cash=100_000.0)

    orders, skipped = build_order_instructions(
        account,
        targets={"600000.SH": 0.005, "000001.SZ": 0.08},
        quotes={"600000.SH": 800.0},
        as_of=AS_OF,
    )

    assert orders == []
    reasons = {entry["symbol"]: entry["reason"] for entry in skipped}
    assert reasons["600000.SH"] == "below_one_lot"
    assert reasons["000001.SZ"] == "missing_quote"


def test_build_orders_sells_position_but_blocks_same_day_buys() -> None:
    account = PaperAccount(
        cash=1_000.0,
        positions={
            "600000.SH": PaperPosition(shares=500, cost_basis=9.0, last_buy_date=date(2026, 7, 21)),
            "000001.SZ": PaperPosition(shares=500, cost_basis=9.0, last_buy_date=AS_OF),
        },
    )

    orders, skipped = build_order_instructions(
        account,
        targets={},
        quotes={"600000.SH": 10.0, "000001.SZ": 10.0},
        as_of=AS_OF,
    )

    assert len(orders) == 1
    order = orders[0]
    assert order.symbol == "600000.SH"
    assert order.side == "sell"
    assert order.shares == 500
    assert order.limit_price == 9.98
    assert skipped == [{"symbol": "000001.SZ", "reason": "t_plus_one_locked"}]


def test_build_orders_downsizes_buys_to_available_cash() -> None:
    account = PaperAccount(cash=1_500.0)

    orders, skipped = build_order_instructions(
        account,
        targets={"600000.SH": 1.0},
        quotes={"600000.SH": 10.0},
        as_of=AS_OF,
    )

    assert skipped == []
    assert len(orders) == 1
    assert orders[0].shares == 100  # only one lot affordable at 10.02 plus commission


def test_order_instruction_round_trip_binds_source_hashes(tmp_path: Path) -> None:
    account = PaperAccount(cash=100_000.0)
    orders, skipped = build_order_instructions(
        account,
        targets={"600000.SH": 0.08},
        quotes={"600000.SH": 10.0},
        as_of=AS_OF,
    )
    source = tmp_path / "targets.csv"
    source.write_text("symbol,target_weight\n600000.SH,0.08\n", encoding="utf-8")
    output = tmp_path / "order_instructions.json"

    write_order_instructions(
        output,
        orders=orders,
        skipped=skipped,
        as_of=AS_OF,
        mode="simulation",
        source_paths={"targets": source},
    )
    payload = load_order_instructions(output)

    assert payload["mode"] == "simulation"
    assert payload["as_of"] == "2026-07-22"
    assert payload["orders"][0]["symbol"] == "600000.SH"
    assert len(payload["source"]["targets"]["sha256"]) == 64


def test_reconcile_matches_within_cash_tolerance() -> None:
    account = PaperAccount(
        cash=50_000.0,
        positions={"600000.SH": PaperPosition(shares=700, cost_basis=10.0)},
    )
    broker_state = {
        "kind": "broker_state",
        "as_of": "2026-07-22",
        "cash": 50_040.0,
        "positions": [{"symbol": "600000.SH", "shares": 700, "avg_cost": 10.01}],
    }

    report = reconcile_broker_state(account, broker_state, cash_tolerance=100.0)

    assert report["status"] == "OK"
    assert report["differences"] == []


def test_reconcile_fails_closed_on_share_and_cash_gaps() -> None:
    account = PaperAccount(
        cash=50_000.0,
        positions={"600000.SH": PaperPosition(shares=700, cost_basis=10.0)},
    )
    broker_state = {
        "kind": "broker_state",
        "as_of": "2026-07-22",
        "cash": 49_000.0,
        "positions": [{"symbol": "600000.SH", "shares": 600, "avg_cost": 10.0}],
    }

    report = reconcile_broker_state(account, broker_state, cash_tolerance=100.0)

    assert report["status"] == "FAILED"
    fields = sorted(diff["field"] for diff in report["differences"])
    assert fields == ["cash", "position"]


def test_build_live_orders_cli(tmp_path: Path) -> None:
    import subprocess
    import sys

    account_path = tmp_path / "account.json"
    account_path.write_text(
        json.dumps({"cash": 100000.0, "positions": {}, "nav_history": [], "last_processed_date": "2026-07-21"}),
        encoding="utf-8",
    )
    targets_path = tmp_path / "targets.csv"
    targets_path.write_text("symbol,target_weight\n600000.SH,0.08\n", encoding="utf-8")
    quotes_path = tmp_path / "quotes.csv"
    quotes_path.write_text("symbol,price\n600000.SH,10.0\n", encoding="utf-8")
    output = tmp_path / "order_instructions.json"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_live_orders.py",
            "--account",
            str(account_path),
            "--targets",
            str(targets_path),
            "--quotes",
            str(quotes_path),
            "--as-of",
            "2026-07-22",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["mode"] == "simulation"
    assert payload["orders"][0]["shares"] == 700


def test_reconcile_cli_fails_closed(tmp_path: Path) -> None:
    import subprocess
    import sys

    account_path = tmp_path / "account.json"
    account_path.write_text(
        json.dumps({"cash": 100000.0, "positions": {}, "nav_history": []}),
        encoding="utf-8",
    )
    broker_state_path = tmp_path / "broker_state.json"
    broker_state_path.write_text(
        json.dumps(
            {
                "kind": "broker_state",
                "as_of": "2026-07-22",
                "cash": 90000.0,
                "positions": [],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/reconcile_broker_state.py",
            "--account",
            str(account_path),
            "--broker-state",
            str(broker_state_path),
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )

    assert result.returncode == 1
    assert "status=FAILED" in result.stdout
