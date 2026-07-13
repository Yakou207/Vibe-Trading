# Project Context

This project is intended to become a small quantitative auto-trading research
system for fintech graduate-school portfolio work.

## Product Goal

- Build a basic A-share-focused quantitative trading system within roughly two
  months.
- Prioritize a practical research system over live brokerage integration.
- Support reinforcement learning later, but only after the data, baseline
  strategy, backtest, and risk-control loop is reliable.
- Use the project as a demonstrable fintech engineering/research artifact.

## Market Scope

- Focus on China A-shares first.
- Use the existing 30-stock STAR Market universe only as a diagnostic fixture.
- Use CSI 300 as the next primary research universe so stock selection,
  benchmark comparison, and generalization are evaluated on a comparable
  market scope. Consider CSI 800 only after the CSI 300 path is reliable.
- Use daily data first. Do not optimize for high-frequency trading.

## Data Source

- Use AkShare as the primary data provider.
- Build around a stable local data schema before adding fallback providers.

## Desired Capabilities

- Initial data collection.
- Data cleaning and local storage.
- Basic NLP analysis and sentiment analysis.
- Baseline strategies using indicators such as RSI, MACD, and volume/order
  signals.
- Indicator-based decision logic.
- Backtesting.
- Dashboard/reporting.
- Risk control, including position sizing, drawdown limits, and A-share trading
  constraints.
- Reinforcement-learning strategy evolution after the baseline research loop is
  working.

## Engineering Preferences

- Prefer simple, working vertical slices over broad empty scaffolding.
- Keep changes surgical and tied to the current research-system goal.
- Use Git frequently for checkpoints.
- The user's GitHub repository may be used as a remote backup once a remote URL
  is configured.

## Strategy Architecture

- Use the scored multi-factor baseline as the primary stock-selection and
  return engine.
- Keep the risk engine responsible for position sizing, portfolio drawdown
  reduction, and forced liquidation.
- Use DQN only as a timing or position-sizing overlay. Do not let RL become the
  sole stock-selection source or increase paper-trading exposure until its
  backend behavior is stable and independently validated.
- Evaluate all strategies primarily against CSI 300. Absolute return alone is
  not evidence of progress.

## Current Implementation Status

### 2026-07-13 stable signal-price correction

- The daily incremental signal-price chain now requires `hfq`. Incremental `qfq` is rejected by
  both collection and processed-snapshot construction because future corporate actions rewrite its
  historical scale and violate the immutable parent-chain assumption.
- A full 439-symbol `hfq` bootstrap produced 530,682 signal rows. Sina supplied 436 scopes; three
  explicit Sina failures (`600705.SH`, `600837.SH`, `601989.SH`) were completed through the Tencent
  backend under a separate resumable manifest. No scope was silently backfilled.
- The formal `hfq` validation passed the same point-in-time health gate: 99.8914% price coverage,
  100% fundamental coverage, 98.4549% price-volume proxy coverage, no stale factor and no detected
  future leakage.
- The earlier 2026-07-13 `qfq` rerun (142.59% risk-controlled return) is rejected as an unstable
  research result. The stable `hfq` rerun returned 118.30% with 9.65% maximum drawdown and about
  1.71 Sharpe; excess return remained positive in all four reported segments. These remain
  historical research results, not proof of deployable profit.
- On 2026-07-13, eight names passed the 70/0.8 entry gate, but the broad-market drop rule emitted a
  `reduce` warning for all 300 active members. The baseline paper account therefore remained at
  100,000 cash with no positions, targets, trades, blocked orders or applied corporate actions.

### 2026-07-11 CSI 300 execution-price update

- The official CSI 300 history has been reconstructed from a 2026-06-30
  official anchor plus 186 regular and temporary adjustment pairs. It contains
  439 unique stocks and 461 membership intervals; every checked effective date
  has exactly 300 active members.
- The five-year formal path now has 526,767 adjusted signal-price rows,
  525,399 point-in-time fundamental rows, and 518,426 explicit price-volume
  proxy rows. The formal health gate passes with 99.8928% price coverage, 100%
  fundamental coverage, no stale decision-time factor, and no detected future
  leakage.
- Historical PE/PB uses the daily AkShare `stock_value_em` path, with a Baidu
  valuation fallback for delisted stocks. Financial metrics remain joined by
  verified public availability date. The price-volume proxy remains visibly
  labeled and never claims to be actual main-capital net flow.
- Backtest execution now separates adjusted signal prices from unadjusted
  transaction and mark-to-market prices. A versioned corporate-action ledger
  applies cash dividends and bonus/transfer shares on ex-dates. Formal runs
  require processed manifests proving `adjust=none` for execution prices and
  recording corporate-action artifact hashes.
- Under the repaired dual-price path, the scored baseline returned 104.09%
  over the observed five-year interval with 12.03% maximum drawdown. The
  shared drawdown controller reduces exposure to 50% after an 8% close,
  liquidates after a 10% close, and uses an unrestricted shadow strategy NAV
  for staged 8%/6% recovery. Its formal CSI 300 run returned 107.17% with
  9.34% maximum drawdown, approximately 1.60 Sharpe, and positive excess
  return in all four reported time segments after modeled costs.
- The drawdown state is persisted in the paper account together with actual
  and shadow books. Fixed tests cover staged re-entry and repeated liquidation
  attempts after a limit-down blocked exit. Target exports now record raw and
  drawdown-scaled weights while paper execution consumes the raw target and
  applies persisted drawdown state exactly once.
- Linear and Torch policy evaluation now share one execution, action-ledger,
  equity, maximum-drawdown, and portfolio drawdown-control path. Daily DQN
  decisions are recorded separately from position-changing trades; export
  prefers an exact-date decision and will not carry a stale decision forward.
  The default trainable backend is Torch; linear fitted-Q remains diagnostic.
- Individual-account dividend tax is now modeled by FIFO acquisition lot and
  settled on sale at 20%/10%/0% for holdings up to one month, up to one year,
  and over one year. A formal tax-aware rerun showed that a 10% liquidation
  trigger left no execution/re-entry buffer and produced 10.592% drawdown.
  Separating the 10% validation limit from a 9% liquidation trigger reduced
  formal maximum drawdown to 9.7278% while retaining 105.53% total return,
  approximately 1.61 Sharpe, and 1,705.92 of modeled dividend tax.
- These are still research results, not deployable-profit proof: unsupported
  corporate actions must fail closed, and eight weeks of continuous paper
  evidence remain required. Paper validation remains baseline-only while the
  RL overlay is disabled.
- The paper account now shares FIFO dividend-tax lots, minimum commission,
  date-specific sell stamp duty, corporate-action processing, actual/shadow
  books, and the 8%/9% drawdown action policy. T-close targets are persisted
  and execute at the next processed session open; close is used only for NAV.
  Duplicate or out-of-order processing dates fail closed.
- A baseline-only account was initialized on the latest available formal date,
  2026-06-30, with 100,000 cash and no RL report. It correctly queued no
  target: the only score above the entry gate, 002311.SZ at 73.5 confidence
  0.8125, was vetoed by the market-wide risk rule after 39 tracked names fell
  more than 3%. This is a reproducible bootstrap record, not the start of the
  eight-week evidence clock; fresh post-close data and cycles are required.
- Corporate-action collection now covers both distributions and CNInfo rights
  issues. The complete five-year CSI 300 ledger contains 2,452 events: 2,444
  distributions and eight rights issues. Eight dividend scopes that failed on
  CNInfo were completed with Sina dividend data while retaining CNInfo rights
  coverage; all 439 scopes passed. Formal runs reject older manifests that do
  not declare both action types.
- The explicit formal rights policy is `do_not_subscribe`; a held rights issue
  without an explicit policy fails closed in both backtest and paper execution.
  None of the eight historical rights events intersected a position in the
  risk-controlled run, so the complete-action result is unchanged: 105.53%
  total return, 9.7278% maximum drawdown, and 1,705.92 modeled dividend tax.
  The authoritative action ledger hash is
  `d02716c22c0f744815378946282650f6be6f582b94a006afdcce1af99df9f082`.

The system now has the engineering shape of a paper-trading research platform:

- The real-data research pipeline, benchmark-relative comparison, DQN
  walk-forward path, CSI 300 / CSI 800 universe ingestion, paper-trading loop,
  and daily monitoring dashboard have been implemented.
- Paper execution models A-share constraints including T+1, suspensions,
  limit-up / limit-down blocking, lot size, minimum commission, date-specific
  stamp duty, and slippage. Formal research signals execute on the next
  available session rather than the signal close.
- DQN rewards and strategy reports support benchmark-relative excess return,
  and resumable DQN checkpoints are available.
- The completed platform branch was merged and pushed to `main` at `a6a63a9`.
  The point-in-time CSI 300 repair is on
  `codex/csi300-point-in-time-factors`, 23 commits ahead of `main` before the
  current paper-bootstrap status update.
- The repair branch now has official-anchor-plus-adjustment historical
  membership reconstruction, immutable raw/processed manifests with SHA-256,
  disclosure-date joins, common as-of factor lookup for scoring/risk/RL,
  fail-closed coverage/variation checks, and a formal CSI 300 orchestration
  command. A fixed fixture reproduces identical factor, score-analysis, and RL
  dataset hashes across two complete runs.

Engineering completion must not be confused with deployable-profit proof. The
latest historical CSI 300 baseline run beats its benchmark and stays inside the
10% drawdown target after modeled costs, but it has not yet passed dividend-tax
modeling or eight weeks of continuous paper validation.

## Current Real-Data Findings

### 0. The repaired data path fails closed on the latest 30-stock diagnostic

- A new 2026-07-10 diagnostic attempted 90 AkShare scopes for the existing 30
  STAR Market stocks over the five-year research interval. All 30 financial
  statement scopes succeeded; all 30 fundamental/valuation scopes and all 30
  individual capital-flow scopes failed because the upstream Eastmoney proxy
  closed the connection.
- The successful statements produced 462 point-in-time fundamental snapshots.
  Statement-derived trailing/annualized ROE has 455 populated rows and
  same-period revenue growth has 396; the fundamental score now has three
  distinct values from 0 to 17.5 instead of being constant at zero. PE/PB still
  require a separately valid point-in-time valuation path. Capital-flow
  materialization produced zero rows.
- The latest preserved health report fails four gates: price coverage
  `0.806766` versus `0.95`, capital-flow coverage `0.0` versus `0.95`, 1,073
  stale fundamental observations, and all-zero capital-flow scores.
  Fundamental row coverage is `0.891751`, with ROE field coverage `0.992839`
  and growth field coverage `0.888683` among the usable snapshots.
- The formal orchestrator stopped before baseline, risk-controlled, RL, or
  benchmark-comparison artifacts were created. This is the intended behavior;
  the failed provider run and health report are evidence, not a strategy run.
- Do not start the full CSI 300 provider fan-out until the failed factor scopes
  can be resumed successfully or a separately validated point-in-time provider
  is added. Current-constituent backfilling is not an acceptable substitute for
  official historical membership.

### 1. The scored baseline produces no trades

- Fundamental scores, worth 35 points, and capital-flow scores, worth 25
  points, are zero for all 30 STAR Market stocks because the fetched data is not
  connected to the scoring inputs.
- Sentiment is effectively constant at 5, leaving technical indicators as the
  only varying component.
- The resulting practical score ceiling is about 45, below the buy threshold
  of 70. Mean confidence is about 0.43, below the 0.8 gate.
- The intended primary return engine therefore remains in cash and trails CSI
  300 by roughly 38 percentage points over the observed period.
- The paper-trading mechanics work, but the starved signal layer produced only
  one board lot and about 3% portfolio exposure. This is not meaningful
  strategy validation.

### 2. Linear DQN shows excess return but misses the risk target

- On the 2024-06 to 2026-06 out-of-sample interval, the linear-Q DQN reports
  about 67-70% total return, 29-32 percentage points of excess return over CSI
  300, and a Sharpe ratio around 1.68.
- Its maximum drawdown is about 17.2-17.7%, materially above the 10% target.
- The result comes from a concentrated 30-stock STAR Market universe during a
  strong STAR Market period, so sector beta is a major confounder. The first
  walk-forward window underperformed CSI 300 by about 9 percentage points.
- Treat this as preliminary positive evidence, not proof of a deployable edge.

### 3. RL backends disagree materially

- The linear-Q backend trades actively, with about 874 trades in the observed
  run.
- The torch DQN walk-forward backend stays almost entirely in cash, with mean
  window return around 3.1% and NAV often flat at 1.0.
- Until reward scale, exploration decay, feature normalization, action
  distribution, and implementation parity explain this divergence, RL signals
  must not be used to increase paper-trading exposure.

### 4. Full CSI 300 Torch diagnostics select cash, not an investable overlay

- The formal five-year CSI 300 RL dataset contains 365,768 point-in-time state
  samples. With 0.1% transition cost, 0.5 drawdown penalty, and shared 8%/10%
  portfolio control, a one-episode three-window diagnostic returned -0.0576%
  mean OOS return. Invested-step rates were only 0.74%-2.93%.
- Increasing training to five episodes did not repair the behavior. All three
  windows were non-positive, mean return was -0.1584%, and invested-step rates
  were 0%, 1.21%, and 0.28%. More training therefore does not explain the
  near-cash result under the current standalone reward and action semantics.
- The linear and Torch evaluators previously duplicated their loops and policy
  reports omitted maximum drawdown, causing walk-forward aggregation to show a
  false zero drawdown. The shared evaluator and explicit action diagnostics fix
  those measurement defects; the remaining near-cash behavior is a model
  outcome, not an accounting discrepancy.
- Torch is the only backend candidate for future checkpointed DQN work, but it
  is not approved for paper exposure. Paper trading must run the scored
  baseline plus the shared risk engine without a DQN report until an overlay
  evaluated specifically on baseline-selected candidates shows stable positive
  risk-controlled excess return across windows and seeds.

## Data Integrity Rules

The next experiments must use point-in-time data and remain reproducible:

- Preserve raw downloaded data as immutable inputs. Write rebuilt features,
  scores, and RL datasets to versioned or run-specific outputs.
- Join fundamentals and financial statements by their public disclosure date,
  not merely by report period. A trading date may only see information that was
  public by that date.
- Align capital-flow, market, sentiment, and price features to the same trading
  calendar. Lag any field that is not known before the simulated decision time.
- Split train, validation, and test periods before fitting scalers, imputers,
  thresholds, feature selection, or reward normalization. Fit on training data
  only and reuse the fitted transform out of sample.
- Keep benchmark series out of stock-selection features unless explicitly
  designed as lagged market-state inputs. Benchmark data may be used directly
  for reward and evaluation.
- Record universe membership, source timestamps, data coverage, missing-value
  handling, parameters, and commit SHA in each research run. Do not silently
  backfill missing historical inputs with current or future values.
- Add coverage and variation checks for every score component. A required
  component that is all-zero, constant, stale, or below the minimum coverage
  must fail the research run rather than quietly produce a strategy report.

## Next Priority Roadmap

The next phase is strategy repair and validation, not additional platform
features. Work in this order:

1. Restore the failed real factor scopes and rerun the 30-stock gate.
   - Resume the immutable `star30-raw-20260710` run after the Eastmoney-backed
     valuation and capital-flow endpoints recover, or add a separately
     validated provider that supplies public availability dates and historical
     rows under the same schema.
   - Rebuild factors under a new processed run id. Require non-constant
     fundamental/capital-flow scores, coverage above the configured thresholds,
     and meaningful target positions before any threshold tuning.

2. Build the official historical CSI 300 membership artifact.
   - Acquire a current official CSI anchor plus every official regular and
     temporary adjustment since the research start date. Preserve source URLs
     and fetch timestamps.
   - Do not use the current 300 constituents for the full five-year history.
     The existing current-universe CSV is suitable only as an anchor after its
     source and as-of date are verified.

3. Rebuild and rerun the full CSI 300 path after steps 1-2 pass.
   - Fetch approximately five years of daily price, fundamental, financial
     statement, capital-flow, and required market-state data for all CSI 300
     constituents.
   - Rebuild features and the RL state dataset under the data-integrity rules
     above, then run the daily research pipeline and DQN walk-forward process.
   - Compare baseline, risk-controlled baseline, and DQN overlay against CSI
     300 using out-of-sample excess return, tracking drawdown, turnover, costs,
     coverage, and walk-forward stability.

4. Close the drawdown-control loop at a 10% portfolio target.
   - Apply the same portfolio-level drawdown state and actions to baseline
     backtests, both RL evaluation backends, target generation, and paper
     trading.
   - Start with explicit rules such as reducing exposure by half near 8%
     drawdown and liquidating risk exposure near 10%, subject to A-share fill
     constraints.
   - Test state persistence, recovery or re-entry behavior, and blocked exits.
     Re-run the return experiment to determine whether positive excess return
     survives the risk controls.

5. Diagnose and select one trustworthy DQN backend.
   - Compare reward magnitude, feature scaling, exploration schedule, action
     frequencies, position transitions, transaction costs, seeds, and
     train/evaluation mode between linear-Q and torch implementations.
   - Add parity diagnostics on a small fixed dataset and explain the no-trade
     behavior before selecting a backend.
   - Do not allow RL to increase paper exposure until repeated walk-forward
     runs show stable behavior and positive risk-controlled excess return.

6. Run paper trading continuously after the repaired strategy passes offline
   checks.
   - Schedule the post-close cycle every trading day and retain targets, fills,
     blocked orders, positions, NAV, benchmark NAV, data-health results, and
     model or configuration versions.
   - Monitor the dashboard daily and investigate missing data, unusual
     turnover, unexplained no-trade days, and execution anomalies immediately.
   - Accumulate at least 4-8 weeks of paper evidence; use eight weeks as the
     minimum gate for live brokerage consideration.

## Validation Gates

Do not integrate QMT / miniQMT, easytrader, or another live brokerage interface
until all of the following hold:

- Paper trading has run for at least eight consecutive weeks of trading days.
- Net performance after modeled commission and slippage has positive excess
  return over CSI 300.
- Portfolio maximum drawdown is no worse than 10% over the validation period.
- The selected strategy is stable across walk-forward windows and is not
  dependent on a single sector regime or one RL backend anomaly.
- There are no unexplained data leaks, stale inputs, missing-factor fallbacks,
  reconciliation failures, or simulated execution anomalies.
- Every daily decision can be reproduced from immutable input data, recorded
  configuration, and a known code commit.

When resuming implementation, start from the failed 30-stock factor scopes and
the preserved health report. Do not add new strategy features until the scored
baseline can trade on complete, point-in-time inputs.
