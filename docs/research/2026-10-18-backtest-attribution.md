# Formal CSI 300 backtest: honest re-evaluation (2026-10-18)

This is a read-only re-analysis of the formal point-in-time CSI 300 run
`outputs/csi300_research/hfq-formal-20260713` (2021-06-15 → 2026-07-13, 1,230 daily returns). The
headline result was +118.3% (17.3% a year), 9.65% maximum drawdown and a Sharpe ratio of 1.71,
against −9.1% for CSI 300. No strategy code, frozen policy, paper account or evidence file was
changed.

Reproduce with:

```bash
.venv/bin/python scripts/analyze_backtest_attribution.py \
  --membership-snapshot data/diagnostics/csi300_current_20260713.csv
```

The first run caches CSI index history in `data/raw/index_history/` and Shenwan industries from
CNInfo in `data/raw/industry/`. After that, `--offline` reproduces a byte-identical
`outputs/research/backtest_attribution/hfq-formal-20260713.json`. The script verifies the report's
SHA-256 against `pnl_curve.json`. Holdings rebuilt from the trade ledger reconcile to the engine's
daily `positions_value` with zero error. Per-stock gross P&L reconciles to the equity change plus
trading costs to the cent.

## Bottom line

**The +118% backtest cannot be used as evidence of skill.** The backtest's risk layer reads each
day's closing data to decide trades that fill at that same day's open. This same-day look-ahead
explains the low beta, the small down-capture and most of the excess return. Fixing the benchmark
also removes about 13 points of excess return. Once timing is measured on the strategy's actual
exposure path, stock selection net of costs is strongly negative. The defensible parts of the
project are its engineering: point-in-time data, fail-closed gates and the hash-linked evidence
chain. Any performance claim has to wait for the paper-validation window. Paper trading does not
share this leak.

## 1. Same-day look-ahead in the risk layer (new finding)

`portfolio_research_runner.py` fills orders at the execution day's open
(`strategy_execution_price = _bar_open(execution_bar)`). It evaluates risk with
`risk_by_key.get((trade_date, symbol))` and `_dynamic_risk_input(close, ...)`, both keyed to that
same execution day. The broad-market rule fires when more than 15 tracked names fall more than 3%,
and that count is only known at the close. The engine still uses it to sell at, or skip buying at,
that morning's open. Position sizing (`starting_equity`) also uses the execution day's closes, a
smaller second leak.

Evidence from the engine's own warnings, which match same-day stock drops:

| Test | Result |
| --- | ---: |
| Days with the broad-market warning ("hot" days) | 489 of 1,231 |
| Closes holding any stock on a hot day | **2 of 489** |
| Buy days whose *execution* day was hot | **0 of 487** (218 had a hot *signal* day) |
| Sell days whose *execution* day was hot | 224 of 349 (1 had a hot signal day) |
| CSI 300 open→close, hot days / calm days | −0.54% / +0.42% per day |
| Open-trade timing gain, (Δexposure at open) × CSI 300 open→close | +0.124%/day, **t = 11.7**, ×4.57 compounded |

A rule that only sees the prior close cannot avoid 487 of 489 bad days. The backtest effectively
knows each morning whether the market will fall that day.

The paper-trading path (`execution/paper_account.py`) fills the previous close's targets at the
open and sizes from open prices, with no same-day risk re-evaluation. It therefore does not share
this leak. This was checked by reading the code, not by a test. Expect paper results to be much
weaker than the backtest.

## 2. Benchmark restated with total return

The formal report compares against the CSI 300 **price** index, while the strategy is credited with
dividends.

| Series | Total | Annualized | Max DD | Sharpe |
| --- | ---: | ---: | ---: | ---: |
| Risk-controlled strategy | +118.3% | 17.3% | 9.65% | 1.71 |
| CSI 300 price (000300) | −9.1% | −1.9% | 39.8% | −0.02 |
| CSI 300 total return (H00300) | **+3.7%** | 0.7% | 35.8% | 0.13 |

Excess return falls from +127.4 to +114.6 points, and from 19.3% to 16.6% a year. The price
benchmark overstated it by 12.8 points. With a 2% risk-free rate, the Sharpe ratio is 1.51 instead
of 1.71.

## 3. Exposure, beta and where the excess comes from

Exposure is the market value of positions divided by equity. It averaged 35.8% (median 8.3%), and
46.6% of closes held no stock at all. The first trade was on 2021-09-07, so this count includes the
opening 2½ months in cash. Earlier quick checks reported 28.5% using a different definition. When
invested, exposure averaged 67%.

| Against H00300 | Value |
| --- | ---: |
| Daily beta / correlation | 0.265 / 0.49 |
| Up capture / down capture | 0.33 / 0.17 |
| Market-model alpha (Newey-West t) | 15.8% a year (t = 3.6) |

Each row below compares the strategy with a benchmark built on H00300 (cash earns 0%, as in the
backtest):

| Benchmark | Benchmark total | Strategy excess |
| --- | ---: | ---: |
| Beta-matched: 0.265 × H00300 + 0.735 × cash | +2.5% | +115.8 pts (16.8% a year) |
| Prior-close exposure path × H00300 (assumes no intraday information) | +13.8% | +104.5 pts |
| **Actual exposure path including open trades × H00300** | **+424.9%** | **−306.6 pts** (−23.1% a year) |

The last row puts the index on the strategy's own exposure path. The overnight leg uses
prior-close exposure and the open→close leg uses post-open exposure, split with 000300 opens. That
leak-driven timing alone would have turned 1.04× into 5.25×. The strategy's picks earned 2.18×
after CNY 36,379 of trading costs (36% of starting capital). Measured against the
timing the strategy actually had, stock selection detracted from returns.

On the 657 days that started invested, the strategy compounded to 1.53× against 1.03× for H00300,
an excess of +50.1 points (beta 0.47). The remaining ×1.43 was earned on the 224 days that *started
fully in cash*, from positions bought at that day's open. That is where the look-ahead shows up.

## 4. Concentration and statistical robustness

| Year | Strategy | H00300 | Beta-matched | Share of total log return |
| --- | ---: | ---: | ---: | ---: |
| 2021 (from Jun 15) | +1.6% | −3.1% | −0.7% | 2% |
| 2022 | +4.4% | −19.8% | −5.3% | 5% |
| 2023 | +1.7% | −9.1% | −2.3% | 2% |
| 2024 | +48.6% | +18.2% | +5.0% | 51% |
| 2025 | +27.9% | +21.0% | +5.4% | 32% |
| 2026 (to Jul 13) | +6.5% | +2.6% | +0.9% | 8% |

- 2024–2026 produced 90% of the log return, and 2021–2023 produced 10%. The bear-market
  "outperformance" came from being out of the market rather than from compounding.
- Over the policy-rally window 2024-09-15 → 2024-10-31 (27 sessions), the strategy gained +33.7%
  against +23.4% for H00300. Excluding that window leaves 1.63× (10.8% a year, Sharpe 1.35, max
  drawdown 9.65%) against 0.84× for H00300.
- Removing the best 5, 10 or 20 days cuts the 2.18× multiple to 1.71×, 1.50× or 1.23×. Four of the
  five best days were 2024-09-26 → 2024-10-08.
- A circular block bootstrap (20-day blocks, 5,000 replications, seed 20260713) gives these 95%
  intervals: annual return 5.2%–34.7%, Sharpe 0.71–2.56, and excess over H00300 4.4%–28.5% a year.
  Annualized excess over the actual-exposure-path index is −32.0% to −15.3%, below zero in every
  replication.
- The Deflated Sharpe Ratio uses seven documented full-sample variants (table below) and an assumed
  cross-variant Sharpe dispersion of 0.5. On that basis it is 0.996, and the probabilistic Sharpe
  ratio against zero is about 1.0. A dispersion of 1.0 lowers it to 0.81 at 7 trials, 0.31 at 20 and
  0.07 at 50. The DSR for the selection series against the actual exposure path is 0.00. All of
  these statistics take the return series as achievable. Section 1 shows it is not, so they describe
  the leaky backtest and cannot rescue it.

## 5. Style and industry attribution

The regressions below explain daily returns using H00300 plus long-short style spreads built from
price indices (Newey-West, 5 lags):

| Specification | Market | Value − growth | Small − large | Div-low-vol − mkt | Daily alpha | R² |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Market only | 0.27 (t 4.1) | | | | 0.063% (t 3.6) | 0.24 |
| + styles, all days | 0.29 (t 4.4) | 0.07 (t 2.4) | 0.02 (t 0.8) | −0.01 (t −0.4) | 0.061% (t 3.6) | 0.25 |
| + styles, invested days | 0.51 (t 6.0) | 0.11 (t 2.3) | 0.03 (t 0.8) | −0.01 (t −0.3) | 0.056% (t 2.1) | 0.43 |

Adding the CSI Dividend spread changes nothing (t = 1.0); its correlation with the dividend-low-vol
spread is 0.92. The strategy has a modest value tilt and no significant size or dividend exposure.
Style indices leave the intercept almost unchanged. That intercept is what the look-ahead produces:
the strategy is out on days when the index falls intraday.

The holdings were rebuilt from the ledger, valued at unadjusted closes and classified with
point-in-time Shenwan level-1 industries:

- 221 stocks traded. On invested days the portfolio held 10.6 names on average (maximum 30). The
  stock-weight Herfindahl index was 0.19, about 5 effective positions. The largest sector averaged
  34% of positions (sector Herfindahl 0.26).
- Average sector weights: basic chemicals 9.4%, banks 8.4%, transportation 8.3%, electronics 7.9%,
  utilities 7.4%, non-bank financials 7.4%, non-ferrous metals 6.7%, autos 6.2%. The CSI 300 on
  2026-06-30 (a current snapshot, not time-matched) held electronics at 24.2% and communications at
  10.8%, so the book was structurally underweight technology.
- Gross P&L by sector (total 154.7k): non-bank financials 28.4k, non-ferrous metals 28.2k, basic
  chemicals 21.6k, electronics 20.7k, power equipment 15.4k. In the September–October 2024 window,
  power equipment (10.4k) and non-ferrous metals (4.7k) led.
- Four names lack a Shenwan 2021 record in CNInfo and are labeled Unclassified, about 1.8% of
  position weight.

## 6. Parameter provenance: the walk-forward segments are not out-of-sample

Every documented variant below was scored on the same full 2021-06-15 → 2026-07-13 window before
the formal run:

| Commit | Variant | Total | Max DD | Sharpe |
| --- | --- | ---: | ---: | ---: |
| 7159c3c | Dual-price baseline, no drawdown control | +104.09% | 12.03% | — |
| 7159c3c | Simple 10% liquidation rule | +4.80% | 10.49% | — |
| f7f9eed | Staged 8%/10% control, shadow-NAV 8%/6% recovery | +107.17% | 9.34% | 1.60 |
| 0210094 | Dividend-tax lots, 10% liquidation trigger | — | 10.592% | — |
| 0210094 | Dividend-tax lots, 9% liquidation trigger | +105.53% | 9.73% | 1.61 |
| d398633 | qfq signal prices (rejected) | +142.59% | — | — |
| d398633 | hfq signal prices (this run) | +118.30% | 9.65% | 1.71 |

| Parameter | Set | Chosen after full-sample results? |
| --- | --- | --- |
| Buy threshold 70 | 2026-06-22 | No. It came with the scored baseline, before any CSI 300 data existed. |
| Minimum confidence 0.8 | 2026-07-04 | Unclear. It came after the STAR30 diagnostic and before the CSI 300 data path. |
| Broad-market rule: >15 names falling >3% | 2026-06-22 | No, but it is mis-scaled. Sized for the 30-stock STAR fixture (half the universe), it was never rescaled for 300 names (5%), and it drives the low exposure. |
| Reduce at 8%, recover at 8%/6% (shadow NAV) | 2026-07-12 | **Yes.** It was designed after the full-sample 12.03% drawdown and the 4.80% simple-liquidation result. |
| Liquidate at 9%, separate from the 10% limit | 2026-07-12 | **Yes.** It was chosen after a full-sample run breached 10% (10.592%). |
| Maximum position weight 8% | 2026-06-16 | No. It was in the initial scaffold. |
| hfq signal adjustment | 2026-07-13 | Partly. The reason was an engineering one, and the switch lowered the headline. |

The four "walk-forward" segments split one full-sample run into consecutive periods. They are not
fitted on earlier data and tested on later data. Because the drawdown policy was chosen after
seeing the full sample's path, positive excess in all four segments is in-sample evidence.

## What can honestly be claimed

- **Defensible:** a reproducible point-in-time CSI 300 research platform with realistic A-share
  costs and constraints, a hash-linked paper-evidence chain, and this audit, which found and
  quantified a material look-ahead in its own backtest.
- **Not defensible:** "+118% versus −9% for CSI 300", "beats the index in every segment", or any
  claim of stock-selection skill.

Suggested next steps, kept outside the paper-validation window:

1. Key risk inputs and sizing to the signal date in the research runner.
2. Rerun the formal backtest as a new, non-counted research run against H00300.
3. Rescale the broad-market rule to the universe size before any re-tuning, and pre-register the
   thresholds and a genuine hold-out period.
