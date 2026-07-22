# CSI 300 QMT live-execution bridge design

Date: 2026-07-22
Branch: `claude/codex-v2-live-trading-cd96e7` (isolated worktree; `main` and the V2 paper-evidence
path are untouched)
Status: design + first implementation milestone

## Problem

The V2 platform is a post-close research and paper-simulation system: daily AkShare bars, a
scored multi-factor decision after close, and a fully internal D+1-open paper execution. There is
no order path to any external trading venue, so it cannot run on QMT/miniQMT or any broker
simulation account.

The strategy itself is daily-frequency by design (signal at T close, execution at T+1 open).
That cadence is compatible with live execution and does not require intraday bars. What is
missing is an execution boundary:

1. translate the canonical account plus the queued `targets.csv` into concrete exchange orders;
2. deliver those orders to a QMT terminal and collect fills;
3. reconcile the broker account against the internal shadow account, failing closed on mismatch.

## Constraints

- QMT/miniQMT (`xtquant`) runs only on Windows next to a broker-installed QMT client. The
  strategy host is macOS, so the bridge is a separate Windows-side process; the two sides share
  only versioned JSON files (a directory synced by any means: shared folder, scp, git, etc.).
- The V2 evidence chain rules stay in force: `live_trading_enabled=false` on the canonical path,
  no mutation of V2 artifacts, and nothing here authorizes real-money trading. The first and
  default execution target is a QMT **simulation** account (`mode="simulation"`); switching the
  bridge to a real account is a human decision outside this codebase's gates and is refused by
  the bridge unless explicitly configured.
- Same economics as paper: lot size 100, T+1 sells, price-limit and suspension awareness.
  Order sizing must mirror `run_paper_trading_day` (value-diff vs one lot, floor lot rounding)
  so that shadow-paper and live fills stay comparable.

## Daily flow (live loop, T+1 morning)

```text
T 17:30  existing post-close cycle (unchanged) -> canonical account + queued targets
T+1 pre-open (Mac)
  scripts/build_live_orders.py
    account.json + targets.csv + realtime/reference quotes
    -> outputs/live_bridge/<date>/order_instructions.json   (schema v1, hash-bound to inputs)
T+1 09:30 (Windows)
  scripts/qmt_bridge/qmt_bridge_windows.py
    reads order_instructions.json, refuses stale dates and non-simulation modes unless configured,
    submits limit orders via xtquant to miniQMT, polls fills
    -> broker_state.json (cash, positions, fills)
T+1 post-close (Mac)
  scripts/reconcile_broker_state.py
    broker_state.json vs shadow paper account -> reconciliation report, FAIL closed on mismatch
```

## Order instruction schema (v1)

`order_instructions.json`:

- `schema_version: 1`, `kind: "live_order_instructions"`
- `as_of`: execution date (the T+1 session)
- `mode`: `"simulation"` (only value the bridge accepts without explicit override)
- `source`: paths + SHA-256 of the account file and targets file used
- `orders[]`: `symbol` (`600000.SH` style, already the xtquant convention), `side`, `shares`
  (lot-rounded), `limit_price` (reference price with a protective offset), `reference_price`,
  `target_weight`
- `skipped[]`: symbols with reasons (`missing_quote`, `below_one_lot`, `t_plus_one_locked`,
  `no_sellable_shares`)

## Reconciliation

`reconcile_broker_state.py` compares, at T+1 close: broker cash vs shadow cash within a cash
tolerance, and broker share counts vs shadow positions exactly. Any discrepancy produces status
`FAILED` with itemised differences; `OK` requires every check to pass. The report is written next
to the instructions. A failed reconciliation stops the live loop until a human investigates —
mirroring the fail-closed philosophy of the V2 evidence chain.

## Explicitly out of scope for this milestone

- Any change to `scripts/run_csi300_post_close.py`, the V2 manifests, auditor, or policy.
- Intraday data, intraday rebalancing, TWAP/VWAP slicing (a single open-auction limit order per
  name is enough at CSI 300 liquidity for a 100k CNY book).
- Real-money accounts, credentials management, and order-routing beyond miniQMT.
- Automatic promotion from paper evidence to live; the 40-session/56-day window and human review
  remain prerequisites.

## File map (new)

- Order layer: `src/fintech_quant/execution/broker.py`
- Order CLI: `scripts/build_live_orders.py`
- Reconcile CLI: `scripts/reconcile_broker_state.py`
- Windows bridge: `scripts/qmt_bridge/qmt_bridge_windows.py` (requires Windows + QMT + xtquant;
  not importable on macOS, kept dependency-free at module import time)
- Tests: `tests/test_broker_orders.py`
