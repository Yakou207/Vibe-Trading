# Strategy Comparison and Diagnostics Design

## Purpose

Upgrade the current Q-learning walk-forward output into a strategy comparison
and diagnostic report. The report should make it clear whether RL v1 is useful,
why it wins or loses, and how it compares with simple non-RL baselines under the
same real backtest engine.

## Scope

This design covers:

- Sharpe ratio in the real backtest metrics.
- A simple RSI/MACD rule baseline.
- A hold-only baseline.
- A comparison report across hold-only, buy-and-hold, RSI/MACD, and Q-learning.
- RL behavior diagnostics including action counts, trade count, state count, and
  buy/sell state summaries.

This design does not cover:

- Dashboard UI.
- DQN/PPO.
- Hyperparameter search.
- Portfolio optimization.

## Report Output

`scripts/run_strategy_comparison_report.py` writes
`outputs/strategy_comparison_report.json`.

Each walk-forward window includes:

- Train/test dates.
- One metrics block per strategy.
- Excess return versus buy-and-hold.
- Sharpe ratio for each strategy.
- Win/loss status versus buy-and-hold.
- RL diagnostics with Q-table state count, action counts, trade count, and top
  states for buy/sell decisions.

## Baselines

- `hold_only`: never trades.
- `equal_weight_buy_and_hold`: existing baseline using the real backtest engine.
- `rsi_macd_rule`: buys when RSI is low-to-mid and MACD histogram is positive,
  sells when RSI is high or MACD histogram is negative, otherwise holds.
- `q_learning_v1`: existing Q-learning strategy trained only on the train window.

## Look-Ahead Controls

- Walk-forward windows remain rolling train/test splits.
- Q-learning bins and Q-table are fit only on train rows.
- All strategies are backtested only on the same held-out test rows per window.
- RSI/MACD uses current-row features only.

## Dashboard Position

Dashboard work should come after this report structure stabilizes. This avoids
building UI around metrics that may still change.

