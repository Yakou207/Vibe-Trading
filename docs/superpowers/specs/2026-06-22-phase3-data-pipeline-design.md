# Phase 3 Data Pipeline Design

## Goal

Build a deterministic A-share daily data pipeline that turns selected-universe daily bars into reusable research features for the scored baseline runner and future DQN training.

## Scope

In scope:

- Load a selected-universe CSV.
- Fetch daily bars through the existing provider registry or an injected provider.
- Persist normalized daily bars to CSV.
- Generate technical indicators from local bars:
  - MA20
  - MA60
  - MA250
  - close above MA20
  - close above MA60
  - RSI
  - MACD
  - daily return
  - rolling volatility
- Persist feature rows to CSV.
- Provide a script entry point for repeatable local refreshes.

Out of scope:

- DQN training changes.
- NLP sentiment models.
- Portfolio optimization.
- Broker or paper-trading execution.
- Live smoke tests against AkShare in CI.

## Architecture

Add `features/technical_indicators.py` for pure, deterministic feature generation from normalized daily bars. Add `data/research_dataset.py` for CSV loading/writing and provider-backed universe collection. Add `scripts/refresh_research_data.py` as the user-facing local refresh command.

The implementation uses the Python standard library only. This avoids adding pandas as a hard runtime dependency while keeping the pipeline easy to test with fixtures.

## Data Contracts

Universe CSV:

- `symbol`
- optional `name`
- optional `sector`

Daily bar CSV:

- `symbol`
- `trade_date`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `amount`
- `source`

Feature CSV:

- all daily bar fields
- `return_1d`
- `ma20`
- `ma60`
- `ma250`
- `close_above_ma20`
- `close_above_ma60`
- `close_above_ma250`
- `rsi14`
- `macd_line`
- `macd_signal`
- `macd_hist`
- `macd_positive`
- `volatility20`

## Indicator Rules

- Moving averages are only emitted after the full rolling window exists.
- `return_1d` is empty for the first row per symbol.
- RSI uses a simple rolling average gain/loss over 14 daily returns.
- MACD uses EMA12, EMA26, and signal EMA9.
- Rolling volatility uses population standard deviation of daily returns over 20 observations.
- Indicators are computed per symbol and sorted by `trade_date`.

## Testing

Tests use fixture rows and fake providers. No test should hit AkShare or Tushare.

Required test coverage:

- Universe CSV loading normalizes symbols.
- Provider collection calls the provider once per symbol and preserves selected-universe data.
- Technical indicators produce expected MA, return, RSI, MACD, and volatility fields.
- CSV writer writes deterministic headers and round-trippable values.
- Refresh script works with JSON fixture input for local/offline refresh.
