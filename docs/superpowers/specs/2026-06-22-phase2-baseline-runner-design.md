# Phase 2 Baseline Runner Design

## Goal

Build a small daily baseline backtest runner that turns the Phase 1 scoring, risk, and drawdown modules into a reproducible research loop. The runner is a benchmark for future DQN work, not a live-trading engine.

## Scope

In scope:

- One-symbol daily bars.
- One daily `StockScore` per bar date.
- Optional daily `RiskInput` per bar date.
- Reuse `ScoredBaselineStrategy`, `evaluate_risk`, and `calculate_drawdown`.
- Produce trades, daily equity, risk warnings, drawdown, and summary metrics.

Out of scope:

- Broker integration.
- Portfolio optimization.
- Intraday data.
- Network data fetching.
- DQN training changes.

## Architecture

Add `src/fintech_quant/backtesting/research_runner.py` as a focused orchestration module. It consumes already-normalized daily bars and precomputed scores. It delegates decisions to the existing scored baseline strategy, delegates risk evaluation to the existing risk engine, and delegates drawdown calculation to the existing drawdown engine.

The runner uses a simple all-in or all-out paper accounting model for a single symbol. This keeps the first benchmark deterministic and easy to compare against DQN later.

## Data Contracts

Daily bar input fields:

- `symbol`: normalized A-share symbol string
- `trade_date`: ISO `YYYY-MM-DD` string or `date`
- `close`: numeric close price

Runner records:

- `BacktestTrade`: trade date, symbol, action, price, shares, cash, position, reason
- `DailyEquity`: trade date, cash, position, close, equity
- `ResearchBacktestResult`: trades, equity curve, risk warnings, drawdown result, summary

## Trading Rules

- Initial cash defaults to `100000.0`.
- Buy action invests all available cash into integer shares.
- Sell action liquidates the full position.
- Hold action makes no trade.
- No fees, slippage, T+1, or lot-size constraints in this slice.

These simplifications are intentional. They make the baseline transparent before adding A-share execution constraints.

## Risk Rules

For each date:

- Look up a `RiskInput`, or use `RiskInput()` when absent.
- Evaluate risk with `evaluate_risk`.
- Pass the resulting `RiskAction` into `ScoredBaselineStrategy`.
- Record emitted warnings with the date.

## Testing

Tests must prove:

- The runner buys when score is above the threshold.
- The runner holds when already positioned and no risk signal is present.
- The runner sells when risk action is `REDUCE` or `LIQUIDATE`.
- Equity curve and drawdown summary are produced.
- Missing score for a bar date raises a clear error.

## File Ownership

- `src/fintech_quant/backtesting/research_runner.py`: new runner models and orchestration.
- `src/fintech_quant/backtesting/__init__.py`: export runner APIs.
- `tests/test_research_backtest_runner.py`: TDD coverage.
- `docs/phase-one-change-report.md`: append Phase 2 status after implementation.
