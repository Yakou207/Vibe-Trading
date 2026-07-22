"""Windows-side QMT bridge: submit order instructions to a miniQMT SIMULATION account.

This script runs only on Windows, next to a broker QMT client with miniQMT
enabled, inside a Python environment that has ``xtquant`` installed. It is the
only component allowed to talk to QMT. It refuses any instruction file whose
``mode`` is not ``simulation`` and any execution date other than today, so the
macOS strategy host can never point it at a real-money account by accident.

Usage (Windows):

    python qmt_bridge_windows.py ^
      --instructions order_instructions.json ^
      --userdata-path C:\\gjzq_qmt\\userdata_mini ^
      --account-id 你的模拟资金账号 ^
      --output broker_state.json

The output ``broker_state.json`` is copied back to the strategy host and fed to
``scripts/reconcile_broker_state.py``.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date
from pathlib import Path

SIMULATION_MODE = "simulation"
FINAL_ORDER_STATUSES = frozenset({50, 53, 54, 56, 57})  # filled/cancelled/rejected xtconstant codes


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit order instructions to miniQMT (simulation only).")
    parser.add_argument("--instructions", required=True)
    parser.add_argument("--userdata-path", required=True, help="QMT userdata_mini directory.")
    parser.add_argument("--account-id", required=True, help="miniQMT SIMULATION account id.")
    parser.add_argument("--output", required=True, help="Where to write broker_state.json.")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    args = parser.parse_args()

    payload = json.loads(Path(args.instructions).read_text(encoding="utf-8"))
    if payload.get("kind") != "live_order_instructions" or payload.get("schema_version") != 1:
        raise SystemExit("unsupported instruction file")
    if payload.get("mode") != SIMULATION_MODE:
        raise SystemExit("refusing to run: instructions mode is not 'simulation'")
    as_of = str(payload.get("as_of", ""))
    if as_of != date.today().isoformat():
        raise SystemExit(f"refusing to run: instructions dated {as_of}, today is {date.today().isoformat()}")

    from xtquant import xtconstant
    from xtquant.xttrader import XtQuantTrader
    from xtquant.xttype import StockAccount

    session_id = int(time.time())
    trader = XtQuantTrader(args.userdata_path, session_id)
    trader.start()
    if trader.connect() != 0:
        raise SystemExit("failed to connect to miniQMT; is the QMT client running in mini mode?")
    account = StockAccount(args.account_id, "STOCK")
    if trader.subscribe(account) != 0:
        raise SystemExit("failed to subscribe trading account")

    submitted: list[dict[str, object]] = []
    for order in payload["orders"]:
        side = xtconstant.STOCK_BUY if order["side"] == "buy" else xtconstant.STOCK_SELL
        order_id = trader.order_stock(
            account,
            order["symbol"],
            side,
            int(order["shares"]),
            xtconstant.FIX_PRICE,
            float(order["limit_price"]),
            "csi300_bridge",
            as_of,
        )
        submitted.append({"order_id": order_id, **order})
        print(f"submitted {order['side']} {order['shares']} {order['symbol']} @ {order['limit_price']} -> {order_id}")

    deadline = time.monotonic() + args.timeout_seconds
    while time.monotonic() < deadline:
        open_orders = [
            o for o in trader.query_stock_orders(account)
            if o.order_status not in FINAL_ORDER_STATUSES
        ]
        if not open_orders:
            break
        time.sleep(args.poll_seconds)

    asset = trader.query_stock_asset(account)
    positions = trader.query_stock_positions(account)
    trades = trader.query_stock_trades(account)
    state = {
        "kind": "broker_state",
        "as_of": as_of,
        "mode": SIMULATION_MODE,
        "account_id": args.account_id,
        "cash": float(asset.cash),
        "total_asset": float(asset.total_asset),
        "positions": [
            {"symbol": p.stock_code, "shares": int(p.volume), "avg_cost": float(p.open_price)}
            for p in positions
            if int(p.volume) > 0
        ],
        "fills": [
            {
                "symbol": t.stock_code,
                "side": "buy" if t.order_type == xtconstant.STOCK_BUY else "sell",
                "shares": int(t.traded_volume),
                "price": float(t.traded_price),
                "traded_at": str(t.traded_time),
            }
            for t in trades
        ],
        "submitted_orders": submitted,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"broker_state={output}")
    trader.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
