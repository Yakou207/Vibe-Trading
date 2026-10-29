# Formal CSI 300 backtest after the look-ahead fix (2026-10-29)

The [2026-10-18 attribution review](2026-10-18-backtest-attribution.md) found a same-day
look-ahead in the research backtest. Its +118.3% headline cannot be used as evidence. This note
records the fix and the rerun. No strategy threshold, score weight, risk limit, drawdown parameter
or cost changed. The paper account, the evidence chain and the counted daily cycle were not
touched. The daily cycle never used this runner.

## Fix

`backtesting/portfolio_research_runner.py`, commit `5514a28`, applies when
`execution_delay_sessions > 0`. The formal run uses one session: signal at the T close, fill at the
T+1 open.

- Static risk inputs are read at the signal date, not the execution date. These include the
  broad-market rule (more than 15 names down more than 3%), information risk and capital-flow
  risk.
- Dynamic risk (position weight, portfolio drawdown, single-position drawdown) and position
  sizing use the book as it stood at the signal close: equity, positions and closes. Corporate
  actions applied on the execution date no longer distort the decision.
- Sells triggered only by risk fill at the open like every other delayed order. Previously they
  filled at that day's close.
- With `execution_delay_sessions = 0` (decide and fill at the same close) the behavior is unchanged.

Three regression tests pin the behavior:

- execution-day risk cannot block a delayed buy, while signal-day risk does block it;
- a sell cannot react to the execution day's close;
- a bonus-share ex-date does not inflate the decision book.

The full suite passes (695 tests).

## Rerun

Run `outputs/csi300_research/hfq-lagfix-20261029` (git `5514a28`, clean tree) uses exactly the same
immutable inputs as `hfq-formal-20260713`: the same manifests, data-health pass, 2021-06-15 →
2026-07-13, CNY 100,000, all modeled costs and individual dividend tax.

| Series | Total | Annualized | Max DD | Sharpe | Trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| Risk-controlled baseline | **−17.0%** | −3.8% | 17.3% | −1.09 | 1,460 |
| Unrestricted baseline | **−34.4%** | −8.3% | 39.5% | −0.78 | 4,244 |
| CSI 300 price (000300) | −9.1% | −1.9% | 39.8% | −0.02 | — |
| CSI 300 total return (H00300) | +3.7% | 0.7% | 35.8% | 0.13 | — |
| *Before the fix (invalid)*: risk-controlled | *+118.3%* | *17.3%* | *9.65%* | *1.71* | *4,336* |

Cross-check: rerunning with `execution_delay_sessions = 0` decides and fills at the same close.
That setup cannot see the future. It is slightly optimistic about fills. Its results agree with
the fixed run: the unrestricted baseline returned −26.1% (39.1% max DD) and the risk-controlled
one −9.2%. So the original result came from the look-ahead, not from the timing convention.

What the attribution script (`scripts/analyze_backtest_attribution.py --run-dir …`) shows on the
fixed run:

- **No selection edge.** On its own exposure path the index lost 2.0%. The picks lost 17.0%. The
  selection effect is −15.0 points, and the open-trade path gives −12.7 points.
- **Costs dominate.** Gross P&L was −CNY 6,908. Trading costs were CNY 10,111 (10% of starting
  capital), at 55.6× turnover. The win rate of closed trades was 32%.
- **The drawdown controller does not hold 10% and leaves the market for good.** It liquidated on
  2022-10-20, re-entered on 2022-11-07 and liquidated again on 2023-05-23. It never re-entered,
  because the shadow book's drawdown (39%) never recovered to the 8%/6% thresholds. 2024–2026 are
  all cash. The realized maximum drawdown is 17.3%, because each controller episode re-bases its
  peak.
- **Statistics.** A circular block bootstrap (20-day blocks, 5,000 replications) gives annualized
  excess over H00300 of −21.4% to +9.2% (point −4.5%). Excess over a beta-matched index is below
  zero in 99.7% of replications. The deflated Sharpe ratio is about 0.

## Conclusion

Once the look-ahead is removed, the scored multi-factor baseline shows no evidence of an edge over
CSI 300 on point-in-time data. It loses to the total-return index, mostly through trading costs.
Its drawdown rule does not meet the 10% target. This is a valid research result produced by the
platform's own audit. It is not an engineering failure.

What follows from it:

- The counted paper-validation window continues unchanged. Its rules forbid tuning during the
  window, and it is the predeclared out-of-sample test. The backtest predicts that it will not pass
  the excess-return gate. Live trading remains out of scope.
- Any new strategy work must start from this corrected runner. It must pre-register thresholds and
  keep a genuine hold-out period. Retuning the 70/0.8 gate or the drawdown parameters on this same
  2021–2026 sample would only overfit it.
