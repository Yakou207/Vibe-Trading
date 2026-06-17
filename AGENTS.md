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
- Prefer a narrow research universe, such as 20-30 stocks from the STAR Market
  or another clearly defined A-share subset.
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

## Reinforcement Learning Validation Rules

These rules are mandatory for DQN and any future reinforcement-learning
strategy work:

- Keep in-sample training and out-of-sample testing strictly separated by
  date before fitting any model, scaler, normalizer, binning threshold, replay
  buffer, or policy parameter.
- Fit DQN scalers and neural-network weights only on the current walk-forward
  train window. Out-of-sample rows may be used only after training, for
  backtesting, diagnostics, and reporting.
- Recompute next-return labels inside each in-sample train window before DQN
  training. Do not use labels precomputed on the full dataset when the label
  for the last train row could reference the first test row.
- Never include label columns such as `target_next_return_1d` or
  `target_action` in model feature columns.
- Report both rolling-window and expanding-window walk-forward validation.
  Do not report only the best validation mode or best window.
- Each validation window report must include `train_start`, `train_end`,
  `test_start`, `test_end`, `train_rows`, `test_rows`, and the validation mode.
- If a daily strategy uses features that require the full same-day OHLCV bar or
  close-derived indicators, it must not claim same-close executable results.
  Either execute at a later tradable bar or label the result as a research-only
  diagnostic.
