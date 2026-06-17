# Real Backtest, Risk Gate, and RL Training Design

## Purpose

Build a verified daily A-share research loop that turns strategy decisions into
cash, positions, trades, equity curves, and comparable metrics before RL
training starts. RL policies must train against the same cost and risk semantics
used by baseline strategies.

## Scope

This design covers:

- A daily portfolio backtest engine for local AkShare daily data.
- A risk gate that enforces practical A-share research constraints.
- A real baseline backtest command using the existing feature table.
- A Gymnasium-compatible buy/sell/hold environment.
- An initial training script that can run without external model libraries.

This design does not cover:

- Live brokerage integration.
- Minute-level or tick-level matching.
- Order book simulation.
- Short selling, margin, futures, or options.
- Deep RL algorithms from stable-baselines or similar packages.

## Assumptions

- Input data is daily OHLCV from `data/processed/akshare_research_features.csv`.
- Orders execute on the current row close price for this first research version.
- Signals are generated per symbol per day and pass through the risk gate before
  execution.
- A-share lot size is 100 shares.
- T+1 means shares bought today cannot be sold until the next trading date.
- The engine uses long-only cash equities.
- The default baseline is equal-weight buy-and-hold across the first available
  trading day, then hold.
- Costs include buy commission, sell commission, sell stamp tax, and symmetric
  slippage.

## Architecture

The core flow is:

```text
feature rows -> strategy decisions -> risk gate -> portfolio execution -> metrics/report
```

The backtest layer owns portfolio state, order execution, costs, T+1 sellable
shares, and metrics. The risk layer decides whether a proposed order is allowed.
Strategies only return buy/sell/hold decisions; they do not mutate cash,
positions, or risk state.

## Components

- `src/fintech_quant/backtesting/costs.py`
  - Defines `CostModel`.
  - Calculates buy/sell cash impact with commission, stamp tax, and slippage.

- `src/fintech_quant/backtesting/portfolio.py`
  - Defines `Order`, `Trade`, `Position`, `PortfolioSnapshot`, and `Portfolio`.
  - Maintains cash, long positions, pending T+1 sellability, trade logs, and
    daily equity snapshots.
  - Enforces lot-size rounding at execution.

- `src/fintech_quant/risk/rules.py`
  - Keeps `RiskLimits`.
  - Adds `RiskDecision` and `RiskGate`.
  - Blocks buys that exceed max symbol weight or drawdown stop.
  - Blocks sells that violate T+1 available shares.

- `src/fintech_quant/backtesting/engine.py`
  - Groups feature rows by date.
  - Marks positions to market.
  - Calls a strategy function for each row.
  - Converts buy/sell decisions into target orders.
  - Routes orders through the risk gate and portfolio.
  - Produces `BacktestResult` with metrics, trades, and equity curve.

- `src/fintech_quant/strategies/buy_and_hold.py`
  - Keeps the existing walk-forward statistical baseline.
  - Adds a real baseline adapter that buys equal-weight positions once and then
    holds.

- `scripts/run_backtest_baseline.py`
  - Runs the real baseline backtest.
  - Writes `outputs/baseline_backtest.json`.

- `src/fintech_quant/training/rl_environment.py`
  - Implements a Gymnasium-compatible single-symbol environment.
  - Uses buy/sell/hold actions and reward as net worth change after costs.
  - Falls back to a local lightweight interface when Gymnasium is not installed.

- `scripts/train_rl_random_policy.py`
  - Runs an initial random-policy training loop.
  - Writes `outputs/rl_random_policy_training.json`.

## Data Flow

Backtesting starts from the feature CSV, sorted by `date` and `代码`. Each date
is evaluated as one portfolio step:

1. Mark existing positions to the latest close.
2. Ask the strategy for decisions on that day's rows.
3. Convert decisions into orders using available cash, prices, and target
   weights.
4. Apply risk checks.
5. Execute allowed orders.
6. Record end-of-day portfolio equity.
7. Unlock T+1 sellable shares after the trading date is complete.

RL training starts from one symbol's feature rows. At each step, the environment
receives one action, applies costs and T+1 constraints through the same portfolio
objects, advances one day, and returns reward from equity change.

## Metrics

The backtest result reports:

- Initial cash.
- Final equity.
- Total return.
- Annualized return using 252 trading days.
- Maximum drawdown.
- Trade count.
- Buy count and sell count.
- Date range.

## Error Handling

- Empty input data raises `ValueError`.
- Missing required columns raises `ValueError` naming missing columns.
- Orders with non-positive price or quantity are rejected before execution.
- Sells above available position are clipped to available shares.
- Buys that cannot afford one lot after costs are skipped.

## Testing

Tests must prove:

- Buy orders pay commission and slippage.
- Sell orders pay commission, stamp tax, and slippage.
- Lot-size rounding prevents odd-lot buys.
- T+1 blocks same-day sells after a buy.
- Max position weight blocks oversized buys.
- Max drawdown stop blocks new buys.
- Baseline backtest creates trades and an equity curve from feature rows.
- RL environment exposes reset/step and changes reward after actions.

