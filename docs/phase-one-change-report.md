# Phase 1 Change Report

Date: 2026-06-22
Branch merged: `codex/a-share-research-system`
Main merge commit: `9b5129a`

## Executive Assessment

The original project had a useful research skeleton and a DQN/RL strategy entry point, but it was not yet a reliable quantitative research system. The main gaps were upstream of RL:

- A-share data access was not stable enough for repeated research.
- The system did not preserve classified information records for policy, announcements, and reports.
- Factor scoring, risk gating, and drawdown accounting were not explicit enough to compare against DQN.
- RL could train on weak or inconsistent state inputs, which creates overfitting risk before any live-trading value.

Phase 1 moves the project from "RL strategy scaffold" to a daily A-share research loop:

```text
A-share data -> information repository -> multi-factor score -> risk warning -> drawdown -> scored baseline strategy
```

This is deliberately simpler than a full HKUDS/Vibe-Trading style agent platform. HKUDS/Vibe-Trading has a broad agent workbench with data tools, research automation, backtest integration, attribution, run libraries, MCP/API surfaces, and web UI workflows. For this project, the professional path is to first make local data, scoring, risk, and backtest contracts dependable, then let DQN compete against a clear baseline.

Reference: https://github.com/HKUDS/Vibe-Trading

## What Changed

### A-share Data Layer

- Added A-share symbol normalization.
- Added a provider registry with `source="auto"` routing to AkShare first.
- Added AkShare daily data provider.
- Added Tushare provider interface with token gating for later account setup.
- Enforced a stable daily-bar schema:
  - `trade_date`
  - `open`
  - `high`
  - `low`
  - `close`
  - `volume`
  - `amount`
  - `source`
- Canonicalized provider dates to `YYYY-MM-DD`.
- Wrapped provider dependency, fetch, and normalization failures in data-provider exceptions.

### Information Repository

- Added classified records for:
  - regulatory policy
  - financial reports
  - company announcements
  - sector events
  - market sentiment
  - selected-universe stock data
- Added JSONL repository storage and deduplication.
- Added retention policy:
  - text information keeps only the recent 3 years
  - selected-universe stock data is retained for RL training
- Added `scripts/fetch_information.py`.
- Chose a practical daily-use approach over a Hermes interface for Phase 1:
  - default source-backed AkShare notice fetcher
  - deterministic JSONL fetcher for reproducible tests and offline loading
  - CLI-level retention pruning after fetch

### Multi-factor Stock Scoring

Added a simple weighted score:

- Fundamental: 35%
  - PE
  - PB
  - ROE
  - growth
- Technical: 25%
  - moving-average state
  - RSI
  - MACD
  - volume confirmation
- Capital flow: 25%
  - main capital direction
  - main outflow days
  - margin financing direction
- Sentiment: 15%
  - limit-up streak
  - dragon-tiger board signal
  - negative event count

The scorer returns component scores, reasons, missing-field tracking, and confidence.

### Risk Warning Engine

Added four risk layers:

- portfolio drawdown
- individual-stock risk
- broad-market anomaly
- systemic risk

Implemented initial thresholds:

- portfolio drawdown >= 15% -> liquidation
- single position weight > 8% -> reduce
- single-position drawdown > 8% -> reduce
- ST warning -> reduce
- goodwill ratio > 30% -> watch
- pledge ratio > 50% -> watch
- main outflow days > 3 -> watch
- index below annual moving average -> watch
- count of names dropping more than 3% > 15 -> reduce

### Drawdown Engine

- Added dated equity-point drawdown calculation.
- Tracks peak, trough, max drawdown, and current drawdown.
- Kept drawdown independent from any strategy so it can evaluate both baseline and DQN later.

### Baseline Strategy

- Added scored baseline strategy.
- Risk action overrides raw score:
  - `LIQUIDATE` -> sell
  - `REDUCE` -> sell/reduce signal
  - otherwise score threshold controls buy/hold
- This gives the DQN agent a practical benchmark instead of letting RL be judged in isolation.

## Current Quality Gate

Final merged `main` verification:

```bash
PYTHONPATH=/Users/yakou/Desktop/Vibe-Trading/src \
  /Users/yakou/Desktop/Vibe-Trading/.venv/bin/python -m unittest discover -s tests
```

Result:

```text
Ran 41 tests in 0.144s
OK
```

Final independent review status:

- Critical: none
- Important: none
- Minor: none
- Ready to merge: yes

## Engineering Notes

- The system is still research-first, not live brokerage execution.
- Daily data is the correct first frequency for this project.
- The DQN path should not be expanded until the baseline loop has enough clean samples and backtest comparisons.
- The information repository is intentionally simple JSONL first. A database can be introduced after the schema stabilizes.
- The AkShare notice fetcher is page-bounded and filters locally by date; it should not be treated as a complete historical archive yet.

## Phase 2 Baseline Runner Update

Phase 2 adds `run_scored_baseline_backtest`, a deterministic one-symbol daily backtest runner for the scored baseline strategy.

The runner:

- consumes normalized daily bars and precomputed `StockScore` values
- accepts optional per-date `RiskInput` records
- delegates decisions to `ScoredBaselineStrategy`
- delegates risk evaluation to `evaluate_risk`
- delegates drawdown calculation to `calculate_drawdown`
- outputs trades, daily equity, dated risk warnings, drawdown, and summary metrics

Current simplifications:

- one symbol only
- all-in/all-out accounting
- no fees
- no slippage
- no T+1
- no lot-size rule
- no price-limit or suspension handling

These simplifications keep the first DQN benchmark transparent. They should be tightened before interpreting performance as tradable A-share performance.

Verification added:

```bash
PYTHONPATH=/Users/yakou/Desktop/Vibe-Trading/.worktrees/phase2-baseline-runner/src \
  /Users/yakou/Desktop/Vibe-Trading/.venv/bin/python -m unittest tests.test_research_backtest_runner
```

Result:

```text
Ran 5 tests
OK
```

## Phase 3 Data Pipeline Update

Phase 3 adds a selected-universe daily data and feature pipeline.

The pipeline:

- loads a selected-universe CSV
- collects daily bars through an injected provider or fixture JSON
- writes normalized daily bars to CSV
- generates technical indicator feature rows
- writes feature rows to CSV for baseline and future DQN research

Generated features:

- `return_1d`
- `ma20`, `ma60`, `ma250`
- `close_above_ma20`, `close_above_ma60`, `close_above_ma250`
- `rsi14`
- `macd_line`, `macd_signal`, `macd_hist`, `macd_positive`
- `volatility20`

The refresh command is:

```bash
python scripts/refresh_research_data.py \
  --source json \
  --input bars.json \
  --universe universe.csv \
  --daily-output data/processed/akshare_research_daily.csv \
  --feature-output data/processed/akshare_research_features.csv
```

Provider mode supports `--source auto`, `--source akshare`, or `--source tushare` with `--start` and `--end`. Tests use fixture mode only, so the suite does not depend on AkShare network availability.

Verification added:

```bash
PYTHONPATH=/Users/yakou/Desktop/Vibe-Trading/.worktrees/phase3-data-pipeline/src \
  /Users/yakou/Desktop/Vibe-Trading/.venv/bin/python -m unittest discover -s tests
```

Result:

```text
Ran 55 tests
OK
```

## Phase 4 Research Run Update

Phase 4 adds a reproducible research-run layer that connects the Phase 1-3 pieces into one offline baseline artifact.

The run command is:

```bash
python scripts/run_research_baseline.py \
  --run-id fixture-run \
  --features data/processed/akshare_research_features.csv \
  --universe universe.csv \
  --output-root outputs/research_runs
```

The report path is:

```text
outputs/research_runs/<run_id>/run_report.json
```

The report includes:

- daily 35/25/25/15 scores
- missing score fields
- risk warnings
- multi-symbol baseline trades
- daily portfolio equity
- drawdown summary
- performance summary

The portfolio baseline adds practical A-share constraints:

- 100-share lots
- default max position weight of 8%
- no same-day sell after buy for the same symbol
- commission and slippage parameters
- risk-triggered exits through the existing risk engine
- actual portfolio and single-position drawdown checks from daily marked equity

DQN remains frozen in this phase. It should be compared against these run reports after the baseline artifacts are stable.

Verification added:

```bash
PYTHONPATH=/Users/yakou/Desktop/Vibe-Trading/.worktrees/phase4-research-run/src \
  /Users/yakou/Desktop/Vibe-Trading/.venv/bin/python -m unittest discover -s tests
```

Result:

```text
Ran 72 tests
OK
```

## Remaining Gaps After Phase 4

1. Add A-share execution constraints to the backtest runner:
   - price limits
   - suspension handling
   - stricter T+1 portfolio accounting across partial fills
2. Convert generated features into RL state datasets.
3. Add DQN-vs-baseline comparison metrics:
   - annualized return
   - Sharpe
   - benchmark excess return
   - walk-forward stability
4. Add richer A-share information sources:
   - exchange announcements
   - company financial reports
   - fund flow
   - margin financing
   - dragon-tiger board
   - sector-level policy events
5. Decide whether Hermes is needed after the fetcher interfaces are stable. For now, scripts are more transparent and safer for daily research operations.
