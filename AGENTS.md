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

The system now has the engineering shape of a paper-trading research platform:

- The real-data research pipeline, benchmark-relative comparison, DQN
  walk-forward path, CSI 300 / CSI 800 universe ingestion, paper-trading loop,
  and daily monitoring dashboard have been implemented.
- Paper execution models A-share constraints including T+1, suspensions,
  limit-up / limit-down blocking, lot size, commission, and slippage, and it
  persists positions and NAV.
- DQN rewards and strategy reports support benchmark-relative excess return,
  and resumable DQN checkpoints are available.
- These changes currently live on
  `codex/real-data-benchmark-evaluation`. Before this roadmap update, the
  completed branch was 13 commits ahead of the local `main` branch and 15
  commits ahead of `origin/main` as of 2026-07-10; this `AGENTS.md` update is
  an additional documentation commit. Merge the branch into `main` before
  starting the next strategy iteration, after rerunning the full test suite and
  reviewing the merge diff.

Engineering completion must not be confused with strategy validation. Current
real-data evidence does not show a strategy that both beats CSI 300 and meets
the portfolio drawdown target.

## Current Real-Data Findings

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

1. Merge the completed branch into `main`.
   - Review the 15 pre-roadmap commits relative to `origin/main` together with
     this documentation update, rerun all tests, merge, and push `main` before
     making new strategy changes.
   - Preserve DQN checkpoint/resume support, but do not reintroduce a separate
     Q-learning strategy path.

2. Connect real factor data to the scored baseline.
   - Reuse the existing `akshare_fundamental`,
     `akshare_financial_statement`, and individual-stock capital-flow
     collectors.
   - Map point-in-time fundamental and capital-flow records into the
     `fundamentals` and `capital_flow` inputs consumed by the scoring engine.
   - Make missing, constant, stale, and low-coverage factor groups visible and
     fail closed when required score components are unusable.
   - Rebuild the 30-stock diagnostic dataset first. Verify that fundamental and
     capital-flow scores are non-constant, the score distribution can cross the
     configured entry gates, and the baseline produces economically meaningful
     target positions before tuning strategy thresholds.

3. Rebuild and rerun the full CSI 300 path.
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

When opening the next implementation thread, start by merging the completed
branch and then repair the fundamental and capital-flow data path. Do not add
new strategy features until the scored baseline can trade on complete,
point-in-time inputs.
