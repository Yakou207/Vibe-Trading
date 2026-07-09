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

## Next Priority Roadmap

The framework and research infrastructure are ahead of the current strategy
evidence. The main bottlenecks are that the latest `main` path has not yet been
run end to end on real data, strategy returns are not yet aligned with the goal
of beating a benchmark, and the execution/paper-trading layer has not started.

Prioritize the next work in this order:

1. Run the current `main` chain end to end on real data.
   - Use the existing 30 STAR Market stocks to rebuild features and the RL
     state dataset.
   - Run `scripts/run_daily_research_pipeline.py` and
     `scripts/run_dqn_walk_forward.py` on the current `main` code path.
   - Produce a real-data baseline report before changing strategy logic.
   - Keep the RL path DQN-only. If the old Q-learning branch has a remaining
     useful checkpoint/resume commit, merge or port only that checkpoint
     capability; do not reintroduce Q-learning as a strategy path.

2. Add "beat the market" benchmark evaluation.
   - `scripts/fetch_market_state.py` can already fetch index state. Connect
     CSI 300 / SSE Composite net-value curves into
     `scripts/compare_strategy_reports.py`.
   - Every strategy comparison should report benchmark-relative excess return
     and benchmark-relative drawdown/tracking drawdown.
   - Do not treat absolute return alone as sufficient evidence for progress.

3. Adjust strategy structure to close the return gap.
   - Use the scored multi-factor baseline as the primary return engine.
   - Keep the risk engine responsible for drawdown control.
   - Use DQN as an overlay for position sizing or timing, not as the only
     stock-selection source.
   - Change DQN reward from absolute return toward benchmark-relative excess
     return. Reuse the existing drawdown-penalty mechanism.

4. Expand the data universe.
   - The current 30-stock STAR Market pool is narrow and has high single-sector
     beta.
   - Expand toward CSI 300 / CSI 800 constituent-level universes so benchmark
     comparison and generalization are meaningful.

5. Build the paper-trading execution loop.
   - Run a daily post-close loop: strategy target positions -> simulated fills
     with T+1 / limit-up / limit-down constraints -> persisted positions and
     net asset value -> daily report.
   - Treat this as the bridge to virtual trading.
   - Delay live brokerage integration such as QMT or easytrader until paper
     trading has run stably for a period.

6. Merge or rebuild the dashboard branch.
   - Use it as a daily monitoring interface for data freshness, portfolio NAV,
     benchmark-relative performance, risk warnings, and DQN walk-forward
     diagnostics.

When opening a new implementation thread, start with items 1 and 2. They define
whether later strategy iteration is moving in the right direction.
