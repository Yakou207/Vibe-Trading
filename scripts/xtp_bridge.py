"""Submit order instructions to the ZTS XTP SIMULATION environment.

Runs inside the linux/amd64 container built from docker/xtp/Dockerfile (the
official XTP bindings have no macOS build). It reads the instruction file
produced by ``scripts/build_live_orders.py``, submits one limit order per
instruction, collects order/trade callbacks, and writes ``broker_state.json``
for ``scripts/reconcile_broker_state.py``.

Refuses any instruction file whose ``mode`` is not ``simulation`` and any
execution date other than today, so the strategy host can never point it at a
real-money account by accident.

Two environment quirks (see docker/xtp/README.md):
  * never call ``api.logout()`` — it deadlocks the interpreter under this
    wrapper, so the process exits via ``os._exit`` instead;
  * process teardown can hang anyway, so success is signalled by the written
    file and the caller enforces a timeout plus ``docker rm -f``.

Usage (inside the container):

    python scripts/xtp_bridge.py \
      --instructions outputs/live_bridge/2026-07-28/order_instructions.json \
      --output outputs/live_bridge/2026-07-28/broker_state.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from time import monotonic, sleep
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.execution.broker import (  # noqa: E402
    BROKER_STATE_KIND,
    SIMULATION_MODE,
    load_order_instructions,
)
from fintech_quant.execution.xtp import (  # noqa: E402
    XTP_BUSINESS_CASH,
    XTP_FINAL_ORDER_STATUSES,
    XTP_PRICE_LIMIT,
    XTP_SIDE_BUY,
    XTP_SIDE_SELL,
    from_xtp_symbol,
    to_xtp_symbol,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit order instructions to XTP (simulation only).")
    parser.add_argument("--instructions", required=True)
    parser.add_argument("--output", required=True, help="Where to write broker_state.json.")
    parser.add_argument("--client-id", type=int, default=1)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument(
        "--allow-stale-date",
        action="store_true",
        help="Permit an instruction date other than today (dry runs outside a session).",
    )
    args = parser.parse_args()

    payload = load_order_instructions(Path(args.instructions))
    verify_instructions(payload, today=date.today(), allow_stale_date=args.allow_stale_date)

    import vnxtptrader

    collector = _Collector()

    class BridgeApi(vnxtptrader.TraderApi):
        def onDisconnected(self, session_id, reason):
            print(f"onDisconnected: session={session_id} reason={reason}")

        def onError(self, data):
            print(f"onError: {data}")

        def onOrderEvent(self, data, error, session_id):
            collector.on_order(data, error)

        def onTradeEvent(self, data, session_id):
            collector.on_trade(data)

        def onQueryAsset(self, data, error, reqid, last, session_id):
            collector.on_asset(data)

        def onQueryPosition(self, data, error, reqid, last, session_id):
            collector.on_position(data)

    api = BridgeApi()
    api.createTraderApi(args.client_id, tempfile.mkdtemp(prefix="xtp-bridge-"), 4)
    api.subscribePublicTopic(2)
    api.setSoftwareKey(os.environ["XTP_SOFTWARE_KEY"])
    api.setSoftwareVersion("vibe-xtp-bridge-0.1")
    api.setHeartBeatInterval(15)

    session_id = api.login(
        os.environ["XTP_TRADER_IP"],
        int(os.environ["XTP_TRADER_PORT"]),
        os.environ["XTP_USER"],
        os.environ["XTP_PASSWORD"],
        1,
        "0.0.0.0",
    )
    if session_id == 0:
        print(f"login FAILED: {api.getApiLastError()}")
        return 1
    print(f"login ok: session={session_id} trading_day={api.getTradingDay()}")

    submitted = submit_orders(api, session_id, payload["orders"])
    await_final_orders(
        collector,
        expected=len(submitted),
        poll_seconds=args.poll_seconds,
        timeout_seconds=args.timeout_seconds,
    )

    api.queryAsset(session_id, 1)
    api.queryPosition("", session_id, 2)
    sleep(5)

    state = build_broker_state(
        as_of=str(payload["as_of"]),
        account_id=os.environ["XTP_USER"],
        asset=collector.asset,
        positions=collector.positions,
        fills=collector.trades,
        submitted_orders=submitted,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"broker_state={output} fills={len(state['fills'])} positions={len(state['positions'])}")
    return 0


def verify_instructions(
    payload: Mapping[str, object],
    *,
    today: date,
    allow_stale_date: bool = False,
) -> None:
    """Fail closed on anything that is not a simulation run for today."""
    if payload.get("mode") != SIMULATION_MODE:
        raise SystemExit(f"refusing to run: instructions mode is {payload.get('mode')!r}")
    as_of = str(payload.get("as_of", ""))
    if not allow_stale_date and as_of != today.isoformat():
        raise SystemExit(f"refusing to run: instructions dated {as_of}, today is {today.isoformat()}")


def submit_orders(
    api: object,
    session_id: int,
    orders: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    submitted: list[dict[str, object]] = []
    for order in orders:
        ticker, market = to_xtp_symbol(str(order["symbol"]))
        request = {
            "ticker": ticker,
            "market": market,
            "price": float(order["limit_price"]),
            "quantity": int(order["shares"]),
            "price_type": XTP_PRICE_LIMIT,
            "side": XTP_SIDE_BUY if order["side"] == "buy" else XTP_SIDE_SELL,
            "business_type": XTP_BUSINESS_CASH,
            "position_effect": 0,
        }
        order_xtp_id = api.insertOrder(request, session_id)
        submitted.append(
            {
                "order_xtp_id": order_xtp_id,
                "symbol": order["symbol"],
                "side": order["side"],
                "shares": int(order["shares"]),
                "limit_price": float(order["limit_price"]),
                "submitted": order_xtp_id != 0,
            }
        )
        print(
            f"submitted {order['side']} {order['shares']} {order['symbol']} "
            f"@ {order['limit_price']} -> {order_xtp_id}"
        )
    return submitted


def await_final_orders(
    collector: "_Collector",
    *,
    expected: int,
    poll_seconds: float,
    timeout_seconds: float,
) -> bool:
    """Wait until every submitted order reached a final status, or time out."""
    if expected == 0:
        return True
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        if collector.final_order_count >= expected:
            return True
        sleep(poll_seconds)
    print(f"WARNING: {collector.final_order_count}/{expected} orders reached a final status")
    return False


def build_broker_state(
    *,
    as_of: str,
    account_id: str,
    asset: Mapping[str, object],
    positions: Sequence[Mapping[str, object]],
    fills: Sequence[Mapping[str, object]],
    submitted_orders: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return {
        "kind": BROKER_STATE_KIND,
        "as_of": as_of,
        "mode": SIMULATION_MODE,
        "account_id": account_id,
        # buying_power is XTP's uninvested cash, matching the paper account's cash.
        "cash": float(asset.get("buying_power", 0.0)),
        "total_asset": float(asset.get("total_asset", 0.0)),
        "positions": [
            {
                "symbol": from_xtp_symbol(str(row["ticker"]), int(row["market"])),
                "shares": int(row["total_qty"]),
                "avg_cost": float(row.get("avg_price", 0.0)),
            }
            for row in positions
            if int(row.get("total_qty", 0)) > 0
        ],
        "fills": [
            {
                "symbol": from_xtp_symbol(str(row["ticker"]), int(row["market"])),
                "side": "buy" if int(row.get("side", XTP_SIDE_BUY)) == XTP_SIDE_BUY else "sell",
                "shares": int(row["quantity"]),
                "price": float(row["price"]),
                "traded_at": str(row.get("trade_time", "")),
                "order_xtp_id": row.get("order_xtp_id"),
            }
            for row in fills
        ],
        "submitted_orders": list(submitted_orders),
    }


class _Collector:
    """Accumulates XTP callbacks; callbacks fire on the api's own threads."""

    def __init__(self) -> None:
        self.asset: dict[str, object] = {}
        self.positions: list[dict[str, object]] = []
        self.trades: list[dict[str, object]] = []
        self.final_orders: dict[object, dict[str, object]] = {}

    @property
    def final_order_count(self) -> int:
        return len(self.final_orders)

    def on_order(self, data: Mapping[str, object] | None, error: Mapping[str, object] | None) -> None:
        if not data:
            return
        status = int(data.get("order_status", 0))
        print(f"order event: {data.get('ticker')} status={status} error={error}")
        if status in XTP_FINAL_ORDER_STATUSES:
            self.final_orders[data.get("order_xtp_id")] = dict(data)

    def on_trade(self, data: Mapping[str, object] | None) -> None:
        if not data:
            return
        print(f"trade: {data.get('ticker')} {data.get('quantity')} @ {data.get('price')}")
        self.trades.append(dict(data))

    def on_asset(self, data: Mapping[str, object] | None) -> None:
        if data:
            self.asset.update(data)

    def on_position(self, data: Mapping[str, object] | None) -> None:
        if data and data.get("ticker"):
            self.positions.append(dict(data))


if __name__ == "__main__":
    # The XTP api spawns non-daemon threads; a plain sys.exit would hang forever.
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
