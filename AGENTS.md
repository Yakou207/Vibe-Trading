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
