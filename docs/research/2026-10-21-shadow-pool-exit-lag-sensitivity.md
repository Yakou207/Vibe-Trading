# Shadow pools: exit-lag sensitivity (2026-10-21)

A reported sensitivity for the two shadow momentum pools (`momentum_pool`, `momentum_pool_v2`). It
does **not** change their predeclared rules, their live state under `outputs/momentum_pool*/`, the
counted strategy, the paper account or any evidence file. Nothing here was used to retune anything.

## Question

Entries are already lagged (trigger on the T close, fill at the T+1 open). Exits decided on the
close (v1: `close_below_ema9`; v2: `close_below_ema9`, `close_below_ema21`, `profit_giveback`,
`time_stop`, `invalidated`) still fill at that same close. Deciding and filling on the same bar is
slightly optimistic. How much does the replay depend on it?

## Option

`step_pool(..., exit_fill="next_open")` in both modules (default `"same_close"`, unchanged). A
close-decided exit is stored on the position as `exit_pending` and sells at the next session's open
with the same 0.05% slippage and the same fees. If that session is suspended, the position is kept
and the exit retried on the following session. Stop and gap exits are intraday stop orders and are
unchanged. A queued exit fills at the open before that day's entries, so its cash and slot are
available to entries at the same open. The closed trade records `decided_on`.

The default path is byte-identical to the code before the option existed:

- `tests/test_momentum_pool_exit_lag.py` pins sha256 hashes of a synthetic v1 and v2 replay that
  were recorded before the change.
- The full default replay with the new code reproduced the original replay's `comparison.json`,
  `v1_pool_state.json` and `v2_pool_state.json` byte for byte. Their sha256 prefixes are
  `2047831e`, `807a9f08` and `944de8a7`.

## Replay

```bash
python scripts/refresh_momentum_pool_v2.py --replay-start 2024-01-02 --exit-fill next_open \
    --pool-root <scratch dir>
```

The window is 2024-01-02..2026-10-20 (675 sessions) with the same daily screens and point-in-time
CSI 300 membership as the baseline replay. The output went to a scratch directory, not
`outputs/momentum_pool*`. `--exit-fill` is rejected without `--replay-start`, so the daily refresh
cannot use it.

### Full period

| | v1 same close | v1 next open | v2 same close | v2 next open | CSI 300 |
| --- | --- | --- | --- | --- | --- |
| Total return | +36.0% | +34.3% | +28.9% | +25.7% | +21.0% |
| Max drawdown | 22.3% | 24.5% | 16.7% | 16.8% | 17.9% |
| Sharpe (daily, ann., rf 0) | 0.62 | 0.64 | 0.62 | 0.58 | 0.48 |
| Closed trades | 572 | 507 | 557 | 557 | — |
| Average trade return | +0.29% | +0.31% | +0.44% | +0.27% | — |
| Win rate | 27.1% | 29.2% | 28.0% | 28.6% | — |
| Average exposure | 78% | 80% | 53% | 59% | 100% |

### Excluding 2024-09-15..2024-10-31

| | v1 same close | v1 next open | v2 same close | v2 next open | CSI 300 |
| --- | --- | --- | --- | --- | --- |
| Total return | +12.6% | +11.2% | +7.5% | +4.5% | -1.8% |
| Max drawdown | 24.2% | 24.5% | 17.7% | 24.7% | 21.0% |
| Closed trades | 566 | 500 | 548 | 548 | — |
| Win rate | 26.5% | 28.6% | 26.8% | 27.6% | — |

The excluded-window series compounds the daily returns outside the window. A drawdown before the
window and one after it can therefore join into one longer drawdown. v2's 24.7% is that kind of
stitched figure, not a drawdown the book actually had. Its full-period drawdown is 16.8%.

## Reading

- **The effect is a few points of return, not a sign change.** v1 loses 1.7 points and v2 loses 3.2
  points. Both still finish above CSI 300 over the full window and in the excluded-window view. v1's
  maximum drawdown worsens by 2.2 points. v2's is unchanged on the full period.
- **The price effect per exit is small.** The mean of next open / deciding close - 1 over the queued
  exits is -0.12% for v1 (263 exits) and -0.03% for v2 (290 exits in the actual book).
  The median is 0, and about half the gaps are negative. Close-decided exits are not systematically
  followed by gap-downs in this sample.
- **Most of the difference is timing, not price.** The default lets a same-close exit free cash and
  a slot that the same day's open entries use, so a slot is reused within one session. With the lag
  that reuse moves to the next open. v1's five slots bind: it closes 65 fewer trades and holds more
  exposure (78% → 80%), and every exit reason falls with it (`gap_below_stop` 101 → 75). In v2, 6
  queued exits filled at an open at or below the stop. v2's slots and cash bind less. Its trade
  count is unchanged, but the brake path differs: 506 instead of 575 `brake_no_entries` skips and 418 instead of 386
  `insufficient_cash` skips.
- **The suspension retry never fired in this window.** No queued exit landed on a suspended
  session. That path is covered only by the synthetic test. No exit was left pending at the end.

## Limits

- This is one replay on the same in-sample 2024-2026 data as the v1 and v2 replays. It describes
  the sensitivity of that replay. It is not evidence for either pool.
- Limit-down opens are not modelled for exits, in either mode. A queued exit always fills at the
  open, which is optimistic on a limit-down day.
- Positions use hfq prices and fractional units, as in the baseline. Board-lot rounding is ignored.
- The counted strategy is unaffected. It already fills at the D+1 open.
