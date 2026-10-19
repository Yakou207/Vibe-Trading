# Shadow momentum pool v2 (2026-10-19)

A shadow research book next to v1. It does not change the counted strategy, the paper account,
the pipeline state or any evidence file, and it writes only under `outputs/momentum_pool_v2/`.

**Read this first.** The v2 rules were predeclared: they are in the module docstring of
`src/fintech_quant/research/momentum_pool_v2.py` and were committed (`c050c90`) before the first
replay ran. They were not tuned afterwards. This is still **one replay**, and it is **in-sample
relative to the earlier v1 replay**: the rules were written in response to v1's drawdown and gap
exits on this same 2024-2026 data. The results below are a description of that replay, **not
evidence** that v2 is better or that it would make money.

## What changed from v1

| | v1 | v2 |
| --- | --- | --- |
| Candidates | The day's top 5 screen results | Watchlist: top 5 added daily, leaves after 10 sessions without a trigger, on `avoid`, or when bought; capped at 20 |
| Positions | ≤ 5, equal weight (equity / 5) | ≤ 8, 0.75% equity risk per trade, ≤ 15% weight, skip if the stop is more than 4% below the fill |
| Exits | Stop, gap below stop, close below EMA9 | Stop, gap below stop, close below EMA9 (EMA21 after 2R), half of peak profit given back after 2R, 15 sessions below 1R, screen turns `avoid` |
| Portfolio | None | Counted engine's drawdown controller: 8% halves risk, 10% stops new entries, recovery measured on an unbraked shadow book (≤ 8% → reduced, ≤ 6% → normal) |

Costs and price basis are the same as v1: hfq prices, fractional units, 0.03% commission (CNY 5
minimum), 0.05% sell stamp duty, 0.05% slippage.

## Replay

Command: `python scripts/refresh_momentum_pool_v2.py --replay-start 2024-01-02`. It runs v1 and v2
on the same daily screens using point-in-time CSI 300 membership, 2024-01-02..2026-10-19 (674
sessions). Output: `outputs/momentum_pool_v2/replay-2024-01-02-2026-10-19/comparison.json`. v1
reproduces the earlier replay. It has 572 trades instead of 571 because the data now runs one
session longer.

### Full period

| | v1 | v2 | CSI 300 (price index) |
| --- | --- | --- | --- |
| Total return | +36.7% | +28.9% | +21.7% |
| Max drawdown | 22.3% | 16.7% | 17.7% |
| Sharpe (daily, ann., rf 0) | 0.63 | 0.62 | 0.49 |
| Closed trades | 572 | 557 | — |
| Win rate | 27.1% | 28.0% | — |
| Average win / loss | +6.30% / −1.94% | +6.60% / −1.95% | — |
| Average exposure | 78% | 53% | — |
| Exits by reason | EMA9 282, stop 189, gap 101 | stop 175, EMA9 118, gap 96, invalidated 89, give-back 52, EMA21 27, time stop 0 | — |

Calendar years: v1 +35.2% / +10.4% / −8.4%, v2 +20.1% / +14.2% / −5.9%, CSI 300 +14.7% / +17.7% /
−9.8% (2024 / 2025 / 2026 to 10-19).

### Excluding 2024-09-15..2024-10-31

Daily returns inside the window are dropped and the rest are compounded. Trades whose holding period
overlaps the window are dropped as well.

| | v1 | v2 | CSI 300 |
| --- | --- | --- | --- |
| Total return | +13.2% | +7.5% | −1.2% |
| Max drawdown | 24.2% | 17.7% | 21.0% |
| Sharpe | 0.34 | 0.25 | 0.05 |
| Closed trades | 566 | 548 | — |
| Win rate | 26.5% | 26.8% | — |
| Average win / loss | +5.78% / −1.94% | +6.03% / −1.95% | — |
| Average exposure | 79% | 52% | — |
| Exits by reason | EMA9 277, stop 188, gap 101 | stop 175, EMA9 118, gap 96, invalidated 82, give-back 51, EMA21 26 | — |

## Reading the replay

- v2 cut the maximum drawdown from 22.3% to 16.7%, mostly by holding less (53% vs 78% average
  exposure). Sharpe is unchanged. The drawdown is still well above the project's 10% gate, so v2
  fails the same gate v1 failed.
- About a third of v1's return comes from the 2024-09/10 rally. Without it, v1 makes +13.2% and v2
  makes +7.5% against −1.2% for the index, and both have drawdowns above 17%.
- The brake was active often: 154 sessions in reduced risk and 164 with no new entries, together
  47% of the replay. The unbraked shadow book ran the same rules for +35.1% with a 19.7% drawdown
  and 0.67 Sharpe. So the brake cost about 6 points of return to save about 3 points of drawdown.
  The replay ends in the no-entries state, which began on 2026-08-12.
- Two rule interactions show up in the numbers. They follow from the predeclared values, and none
  of them was changed:
  - Risk sizing never binds at full risk. A 0.75% risk would exceed the 15% weight cap at any stop
    distance below 5%, and the 4% stop filter rules those out. So every full-risk entry is 15% of
    equity, or less when cash runs short. Risk sizing only matters in the reduced state.
  - 8 × 15% = 120%, so cash runs out before the 8-position cap is reached: 386 queued entries were
    skipped for insufficient cash, and the book averaged 3.65 positions.
- The time stop never fired. The average hold was 4.4 sessions, so the EMA9 trail almost always
  exits a position long before it reaches 15 sessions.
- Gap-below-stop exits barely moved (101 → 96). None of the v2 exit rules address the T+1
  overnight gap problem the v1 report identified.
- The pool earns hfq total return and the benchmark is a price index without dividends, so the
  comparison is slightly tilted toward the pool, as in v1.

## Forward

v2 was initialized forward on 2026-10-19 as a fresh CNY 100,000 book in the normal brake state. It
does not carry over the replay's ending state. Five watchlist triggers (600016, 000001, 600926,
001965, 000651) are queued for the 2026-10-20 open. v1 keeps running unchanged, so the two books can
be compared on unseen sessions. Refresh v2 once per closed session, after the counted cycle and the
v1 refresh:

```bash
python scripts/refresh_momentum_pool_v2.py
```

The picker page (`/picks`) shows v2 next to v1: brake state, the watchlist with each name's age,
queued entries, each position's R multiple, peak R, active trail and give-back level, the time-stop
countdown, and recent exits with their reason codes.

Changing any v2 rule would make a v3 with its own predeclaration. It should not be done by editing v2
in place, and forward v2 sessions should not be used to tune it.
