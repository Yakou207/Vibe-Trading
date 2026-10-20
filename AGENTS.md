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

### 2026-10-20 second counted session

- The 2026-10-20 cycle was accepted (`COLLECTING`, `valid_sessions=2`). The first attempt failed closed
  on one transient Sina failure (`603993.SH`) with the account unchanged; a plain resume completed it.
- The five queued targets filled at the open (CNY 25 modeled cost). NAV 99,904.47 (-0.10%) against
  CSI 300 -0.44%. Seven targets at 8% each are queued for the 2026-10-21 open.
- Daily runs were still manual because the Codex automation is `PAUSED` and the launchd wrapper was
  not installed. The wrapper is now merged on `main` and was installed the same evening (kickstart test: `up_to_date`).

### 2026-10-19 first counted session of the new epoch

- The 2026-10-19 post-close cycle completed and the audit returned `COLLECTING` with
  `valid_sessions=1`: the first accepted date of epoch 2 (cycle manifest `27ce354d25d0f61e44f49e87a0a9ed15646833483ef7e50019b3f1f84515e1a7`).
- Two operational failures preceded it and both failed closed with the account unchanged. Sina raises
  instead of returning nothing for a no-trade range, so the suspended `601059.SH` failed the
  signal-price stage. A Sina failure now counts as empty only when Tencent independently confirms no
  trades in the same range. The second failure was a transient proxy 503 on one dividend scope,
  which a plain resume fixed.
- The account stayed all cash (no targets were queued at the anchor): NAV 100,000 against CSI 300
  +0.09%. Five targets at 8% each (601877, 600938, 601088, 300832, 601018) execute at the
  2026-10-20 open.

### 2026-10-17 fresh validation epoch via all-cash bridge

- The canonical account stopped at 2026-07-21 (CNY 100,000 cash, no positions or tax lots,
  `normal` drawdown regime, seven queued targets). Replaying the roughly 60 missed sessions one
  provider cycle at a time would add no economic information for an all-cash account.
- `scripts/bridge_csi300_paper_epoch.py` collected 2026-07-22 through 2026-10-16 as one immutable
  increment chained to the 2026-07-21 manifests, required fresh data health (price coverage
  99.8879%, fundamental 100%, capital-flow proxy 98.53%, zero leakage, zero stale factors), cancelled
  the seven stale targets in `bridge_manifest.json`, moved the account date to 2026-10-16, and
  created the non-counted schema-2 anchor `anchor-20261016-epoch-2`. It supersedes the original
  anchor, the 2026-07-21 cycle and audit, and the bridge record. No existing anchor, cycle, or
  report was modified. The bridge refuses any account with positions, tax lots, or a non-normal
  regime and restores the canonical files on failure.
- The bridge exposed a daily-chain blocker: `601059.SH` has no price after 2026-09-14 in both
  Sina and Tencent data, and the decision report required 300 current feature rows. The report now
  accepts at most three members that both independent price sources confirm as suspended, lists
  them with their last trade date, and never scores them. Any other gap still fails closed.
- The new epoch audit is `NO_EVIDENCE` with zero sessions. Day 1 is the 2026-10-19 post-close run
  of `scripts/run_csi300_post_close.py`; it counts only if the audit returns `COLLECTING`.
  DQN exposure and live trading remain disabled.

### 2026-07-27 V2 evidence-chain repair

- The same-date processed-factor reuse bug is repaired. Reuse now requires the raw-parent,
  trading-calendar, and signal-price-feature SHA-256 values to match; otherwise the pipeline creates
  a new immutable `-retry-N` processed run. The decision-report equality gate is unchanged.
- Validation epochs can now be superseded explicitly. A schema-version-2 non-counted anchor
  snapshots the current account/state, hash-references the old anchor, latest cycle, and latest
  validation report, and sets an explicit active `evidence_parent` without modifying old evidence.
- The daily entrypoint now rejects a missing, duplicate, out-of-order, or non-session CSI 300 date
  before paper execution. A successful audit atomically mirrors the cycle-local report to the root
  status and records the immutable cycle-local reference in pipeline state; same-date replay
  refreshes only this audit reference.
- Supersession preserves the original formal run/comparison evidence even after incremental
  manifests advance. Its current benchmark must contain the canonical account date.
- No provider-backed cycle or evidence mutation was performed as part of this code repair.
  Read-only inspection on 2026-07-27 found the canonical account/state dated 2026-07-21, three
  preserved failed cycles (2026-07-15, 2026-07-16, and 2026-07-21), and zero accepted continuous
  sessions. Historical or delayed catch-up work must not be counted as fresh operational evidence.
- DQN exposure and live trading remain disabled. The next accepted evidence date requires an
  explicit fresh epoch and a cycle for exactly the next CSI 300 session after its active parent.

### 2026-07-15 CSI 300 PnL dashboard and active blocker

- `main` and `origin/main` were aligned at `5a6a9f2` before this documentation update. The formal
  dashboard now includes an interactive PnL curve backed by a hash-recording `pnl_curve.json`.
  Its 1,231 daily points cover 2021-06-15 through 2026-07-13 and compare the risk-controlled
  baseline, unrestricted baseline, and normalized CSI 300 benchmark on the same CNY 100,000 base.
- This chart is the formal point-in-time CSI 300 HFQ backtest, not the old 30-stock STAR Market
  diagnostic and not accumulated paper-account performance. The ending values are CNY 218,295.88
  for the risk-controlled baseline, CNY 215,321.64 for the unrestricted baseline, and CNY 90,880.26
  for CSI 300. Historical results do not prove future profit.
- The PnL artifact records the source hashes of both formal run reports and the benchmark. Daily V2
  cycle manifests hash-bind the optional curve, and same-date replay verifies it. The dashboard uses
  pinned Chart.js 4.5.1 while keeping the curve data embedded locally.
- The 2026-07-14 17:30 retry completed both signal-price and execution-price scopes for all 300
  active members. Decision-report generation then failed closed because the factor manifest's
  trading-calendar hash did not match the refreshed benchmark. No account/state mutation or audit
  occurred; the formal account remains at 100,000 cash, dated 2026-07-13, with zero valid sessions.
- The immediate task is to reproduce the calendar-hash mismatch, add a regression test, make the
  minimum repair without altering immutable manifests, and rerun only the fixed CSI 300 post-close
  entrypoint for a fresh eligible session. Do not tune strategy thresholds, restart the STAR30
  diagnostic, enable DQN exposure, or connect a live broker while this evidence-chain blocker exists.
- `handoff.md` is the operational source for exact commands, current hashes, artifacts, and the
  new-conversation resume prompt.

### 2026-07-14 CSI 300 paper-evidence V2

- A non-counted immutable validation anchor now snapshots and hashes the formal paper account,
  pipeline state, formal run manifest, benchmark comparison, and CSI 300 benchmark before the
  evidence clock starts.
- Counted post-close cycles use schema-version-2 manifests. They bind the exact parent record,
  material inputs, approved baseline-only policy, account transition, targets, paper report, and
  dashboard. The first fresh cycle chains to the anchor; later cycles chain to the prior cycle.
- Paper execution now defaults to the same 0.05% slippage as the formal backtest. V2 additionally
  fixes 0.03% commission, CNY 5 minimum commission, date-specific sell stamp duty, individual FIFO
  dividend tax, `do_not_subscribe` rights handling, 8% maximum stock weight, and the 8%/9%/10%
  drawdown policy. DQN exposure and live trading remain disabled.
- The deterministic auditor verifies hashes, account continuity, CSI 300 trading-session coverage,
  data health, point-in-time input references, 300-member scope, D+1 open execution, costs,
  corporate actions, NAV, drawdown, turnover, CSI 300 excess return, and anchored walk-forward
  excess. Its strongest result is `ELIGIBLE_FOR_REVIEW`, never live-trading authorization.
- The 2026-07-13 bootstrap and every V1 or rejected qfq record remain non-counted. The eight-week
  evidence clock is still zero until the first fresh post-anchor V2 cycle passes its audit.
- Daily collectors now limit incremental requests to membership intervals that overlap the requested
  dates, while five-year rebuilds still cover every historical member. Failed immutable stages resume
  only missing scopes; a price batch with no rows is never accepted or reused as a completed day.
- The pre-automation 2026-07-14 attempt completed the 300-member, factor, and corporate-action
  scopes, but both price providers still ended at 2026-07-13. The price freshness gate rejected the
  day before account or state mutation. The later 17:30 retry completed both 300-member price
  scopes, then stopped on the factor/benchmark trading-calendar hash mismatch described above.

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
- The original platform branch was merged to `main` at `a6a63a9`. The subsequent point-in-time,
  execution, V2 evidence, and PnL-dashboard work is also on `main`; use the current status section
  above rather than the old feature-branch distance as the source of truth.
- The point-in-time repair added official-anchor-plus-adjustment historical
  membership reconstruction, immutable raw/processed manifests with SHA-256,
  disclosure-date joins, common as-of factor lookup for scoring/risk/RL,
  fail-closed coverage/variation checks, and a formal CSI 300 orchestration
  command. A fixed fixture reproduces identical factor, score-analysis, and RL
  dataset hashes across two complete runs.

Engineering completion must not be confused with deployable-profit proof. The
latest historical CSI 300 baseline run beats its benchmark and stays inside the
10% drawdown target after modeled costs, individual FIFO dividend tax, and the
complete distribution/rights ledger. It has not passed eight weeks of continuous
paper validation.

## Historical Diagnostic Findings

The findings below are retained to explain why the STAR30 fixture was rejected as primary evidence.
They describe the 2026-07-10 diagnostic and do not override the current CSI 300 status or roadmap
above.

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
- At that time, the full CSI 300 provider fan-out was held until the point-in-time factor path and
  official historical membership were available. Both were subsequently completed; the rule
  against current-constituent historical backfilling still applies.

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

The historical membership reconstruction, CSI 300 formal backtest, drawdown-control loop, and V2
paper-evidence platform are complete. The next phase is operational validation, not more platform
features or a return to the STAR30 diagnostic. Work in this order:

1. Fresh validation epoch: done on 2026-10-17 (`anchor-20261016-epoch-2`, all-cash bridge).
   - Future gaps with an all-cash account use `scripts/bridge_csi300_paper_epoch.py`; gaps with open
     positions still require explicit supersession plus non-counted catch-up.

2. Produce the first fresh counted V2 cycle.
   - Use only `scripts/run_csi300_post_close.py` after the eligible A-share session closes.
   - Require the date to be exactly the next CSI 300 session after the active evidence parent.
   - Verify the schema-version-2 manifest, parent and account hashes, data health, targets, paper
     report, dashboard, account/state dates, and deterministic audit.
   - Record a counted date only if the auditor accepts the complete cycle. Failed and partial dates
     remain non-counted evidence.

3. Accumulate the full paper-validation window without strategy drift.
   - Run after every trading session and retain targets, fills, blocked orders, positions, actual and
     shadow NAV, benchmark NAV, data health, model/configuration versions, and immutable parents.
   - Require at least 40 valid trading sessions spanning at least 56 calendar days.
   - Investigate missing data, unusual turnover, unexplained no-trade days, corporate actions, and
     reconciliation failures immediately. Do not tune thresholds while collecting the window.

4. Review the completed evidence against the fixed gates.
   - Require positive net CSI 300 excess return, maximum drawdown no worse than 10%, continuous
     evidence, and stable behavior across the predeclared walk-forward segments.
   - Review costs, turnover, sector/regime dependence, every failed gate, and every operational
     anomaly. `ELIGIBLE_FOR_REVIEW` is not live authorization.

5. Strengthen independent replay before any brokerage work.
   - Independently replay FIFO dividend-tax lots, corporate-action decisions, and account
     transitions from immutable parents rather than trusting reported daily aggregates alone.
   - Consider stronger crash recovery and external signed/WORM evidence retention only after the
     daily V2 chain is operating reliably.

6. Keep DQN and live trading outside the active path.
   - Diagnose the linear/Torch behavior divergence only as a later research task.
   - Do not let DQN increase paper exposure until a baseline-candidate overlay shows stable positive
     risk-controlled excess return across windows and seeds.
   - Do not integrate QMT, miniQMT, easytrader, or any live broker until every validation gate below
     passes and a human explicitly authorizes a separate live-integration phase.

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

When resuming implementation, start from the canonical CSI 300 account/state, the latest V2 audit,
and the preserved 2026-07-14 calendar-hash failure described above. The 30-stock STAR Market set is
only a diagnostic fixture and must not replace or block the CSI 300 paper-validation path.
