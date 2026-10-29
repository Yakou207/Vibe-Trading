# Intraday trigger monitor for the shadow pool v2 watchlist (2026-10-29)

Research only. The v1/v2 shadow pools confirm the Luk setup at the T close and fill at the T+1
open. Luk buys intraday on the reclaim with the stop at the day's low. This monitor measures the
difference going forward, without changing the predeclared daily rules, the counted paper account,
the pipeline state or any evidence file. It is not backtested: minute data covers only a few days,
so evidence accumulates from the first recorded plan.

Code: `src/fintech_quant/research/momentum_intraday.py` (rules),
`scripts/monitor_momentum_intraday.py` (commands), picker panel 盘中触发监控.

## Daily use

```bash
python scripts/monitor_momentum_intraday.py plan      # pre-market, after the v2 pool refresh
python scripts/monitor_momentum_intraday.py watch     # 09:30-15:00 Shanghai; polls once a minute
python scripts/monitor_momentum_intraday.py compare   # any time after the next post-close cycle
```

Outputs, all under `outputs/momentum_pool_intraday/` (gitignored):

- `<date>/plan.json`: written once. A rerun with different content is refused.
- `<date>/triggers.json`: rewritten after every poll; `watch` resumes from it and checks that it
  belongs to the plan (SHA-256).
- `ledger.json`, `comparison.json`, `comparison.md`: rebuilt by `plan` and `compare` from the plan
  and trigger files plus the latest point-in-time daily data. `comparison.md` is the running note.

`plan` refuses to run when the v2 pool is not at the pipeline's latest session, and on weekends.
`watch` refuses any day other than its own. No scheduler hook is committed.

## Rules

1. **Plan.** For each v2 watchlist name, `analyze_at` on the latest pipeline session T gives the
   confluence zone and supports (9/21/50 EMA, AVWAP from the six-month swing low/high, prior
   pivot, unfilled gap). Levels are hfq; the plan also stores them on the unadjusted scale (hfq ×
   unadjusted/hfq close at T), plus T's unadjusted close and the limit-up price. A name is armed
   when its T state is `setup` or `trigger` and its zone has at least two supports.
2. **Trigger.** A minute price at or below the zone top, then a later minute above it that is not
   at limit-up (within 0.5% of the limit, as in v1). Time, price and the low so far are stored.
3. **Fill.** The first minute that appears after the poll that detected the trigger (normally the
   next minute) plus 0.05% slippage. A fill at limit-up, or at or below the low so far, is
   skipped. A trigger still waiting at the close is `unfilled`.
4. **Stop.** The low so far, raised to 4% below the fill when the low is further away
   (`stop_capped`). The daily rule instead rejects a trigger whose stop is over 4%; the flag lets
   the comparison separate those cases.
5. **Ledger.** Each armed name and session D has up to two legs, both exited with the v1 daily rule
   from the session after entry (A-share T+1): an open at or below the stop sells at the open, a
   low through the stop sells at the stop, otherwise a close under the 9 EMA sells at the close.
   - `intraday`: entered on D at the simulated fill.
   - `daily` (`next_open`): only when the daily rule triggers at D's close; it buys at the next
     session's open with v1's skip rules (suspended, limit-up open, open at or below the stop).
   This daily leg is computed in the ledger, not read from the v2 book, so it has no cash, slot
   or risk-sizing limits and the two legs differ only in entry timing and stop.
   Returns use hfq prices, 0.03% commission (no CNY 5 minimum, since legs have no notional),
   0.05% sell stamp duty and 0.05% slippage per fill.

## Known approximations

- Minute prices are minute closes from `live_intraday` (Eastmoney, then Sina), so the low so far
  is the lowest minute close. The true tick low can be lower, so the stop may be slightly tight.
- The zone uses T's levels all day. The daily rule recomputes the EMAs with D's close.
- Intraday entries are converted to hfq with T's ratio. On an ex-dividend day D, the unadjusted
  prices step down and that conversion is off by the distribution. The ledger does not correct it.
- Names that triggered at T are still armed on D (the v2 book buys them at D's open). An
  intraday trigger on D is a separate signal from T's.

## First live check

On 2026-10-29 at 14:53, a scratch plan (reference session 2026-10-28) armed 601088.SH, 600025.SH and
601398.SH. One `watch --once` poll returned all three from Eastmoney. Their minute prices all
stayed above their zone tops, so there was no trigger. This check was in a scratch directory and
is not part of the ledger.
