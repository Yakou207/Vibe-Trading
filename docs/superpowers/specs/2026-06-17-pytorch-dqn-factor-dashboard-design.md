# PyTorch DQN Factor Dashboard Design

## Purpose

Build the next research-system vertical slice by adding a PyTorch DQN strategy,
a first-class factor library and factor diagnostics report, and a local
dashboard that combines factor quality with RL training and backtest outcomes.

This is a research artifact, not a production trading system. The goal is to
make DQN comparable against the existing Q-learning, RSI/MACD, buy-and-hold,
and hold-only baselines under the same daily A-share backtest constraints.

## Scope

In scope:

- Install PyTorch in the current `.venv`.
- Add `torch` to the project RL dependency group.
- Add a PyTorch DQN v1 trainer with epsilon-greedy exploration and decay.
- Add replay memory, a target network, and deterministic seeding controls.
- Expose DQN through the existing `Strategy.decide()` interface.
- Add `dqn_v1` to the strategy comparison report while keeping `q_learning_v1`.
- Add a factor library that names default technical factors and groups.
- Produce a factor diagnostics JSON report with IC, Rank IC, coverage, and
  factor metadata.
- Generate a static local HTML dashboard from existing JSON outputs.

Out of scope:

- Live brokerage integration.
- Intraday or high-frequency data.
- New external data providers.
- Real NLP model training.
- Hyperparameter search beyond a small configurable DQN run.
- Replacing Q-learning entirely.

## Assumptions

- Source data is the existing local `data/processed/akshare_research_features.csv`.
- The first DQN version should optimize for reproducibility and integration,
  not maximum model performance.
- PyTorch CPU training is acceptable for this local research workflow.
- Factor diagnostics should avoid adding SciPy unless required by PyTorch
  transitive dependencies; Spearman Rank IC can be computed by ranking with
  pandas and then using Pearson correlation.
- The dashboard should be a portable static HTML file under `outputs/`, because
  the project has no existing web app or BI destination.

## Architecture

The implementation adds three focused layers.

1. `fintech_quant.training.dqn` owns DQN training, model configuration,
   replay memory, feature scaling, and the `DQNStrategy` adapter.
2. `fintech_quant.features.factor_library` and the existing
   `factor_diagnostics` / `factor_report` modules own factor metadata and
   diagnostic payloads.
3. A dashboard report module owns local HTML rendering from bounded JSON
   artifacts already produced by scripts.

The existing backtesting engine remains the integration point for strategy
evaluation. DQN does not bypass A-share constraints; it emits buy/sell/hold
decisions and the backtest layer applies lot sizing, costs, T+1 sellability,
position limits, and drawdown gates.

## DQN Design

The DQN state vector uses the numeric feature columns already produced by
`features.indicators.feature_columns()`, limited to columns present in the
training frame. A fitted scaler stores per-feature mean and standard deviation
from the training window only. Test rows use the training scaler, preserving
walk-forward separation.

The model is a small MLP:

- input dimension: selected feature count plus a `position_flag` feature
- hidden layers: two configurable hidden layers, default `(64, 32)`
- output dimension: three Q values for `hold`, `buy`, `sell`

Training uses:

- epsilon-greedy action selection
- exponential epsilon decay with a minimum epsilon floor
- replay memory with random mini-batches
- target network copied from policy network every N steps
- Bellman target: `reward + gamma * max(next_q)`
- reward compatible with existing Q-learning reward logic, including trade
  penalty and optional drawdown penalty

The first version trains from sorted symbol/date rows and constructs transitions
from `target_next_return_1d`. It does not simulate full portfolio state during
training; the full portfolio effects are measured during backtesting.

## Strategy Comparison

`run_strategy_comparison_report()` keeps the existing strategies and adds
`dqn_v1`. Each walk-forward window trains Q-learning and DQN only on train rows
and backtests all strategies on the same held-out test rows.

The report adds DQN configuration and diagnostics:

- training episodes
- epsilon, minimum epsilon, epsilon decay
- replay memory size
- batch size
- target update interval
- feature columns
- decision action counts
- trade action counts

This keeps Q-learning as a visible baseline so the dashboard can show whether
the DQN enhancement improves or destabilizes the RL strategy.

## Factor Library And Diagnostics

The factor library defines named factor specs grouped by research role:

- momentum: `return_5d`, `return_20d`, `return_60d`, `macd_hist`
- trend: `close_to_ma_20`, `close_to_ma_60`, `ma_20_slope`, `ma_60_slope`
- risk: `volatility_20`, `high_low_range`
- volume: `volume_ratio_20`, `turnover`
- mean-reversion / oscillator: `rsi_14`, `close_position`

Diagnostics compute:

- IC: Pearson correlation with `target_next_return_1d`
- Rank IC: Pearson correlation of ranked factor and ranked target
- coverage: non-null usable rows divided by total rows
- direction: positive, negative, or neutral based on IC sign
- group and description from the factor library

The factor report remains JSON-first so the dashboard, tests, and future report
formats consume the same payload.

## Dashboard

The dashboard is a static HTML file generated under
`outputs/research_dashboard.html`. It reads structured payloads generated by
scripts and embeds compact tables and simple CSS. No JavaScript framework is
introduced.

Default sections:

- data coverage and source freshness
- strategy KPI comparison across latest walk-forward windows
- DQN vs Q-learning vs buy-and-hold summary
- RL training configuration and warnings
- factor IC and Rank IC leaderboard
- factor coverage table

The dashboard is intentionally compact and presentation-ready for a portfolio
demo. It should make weak DQN performance visible rather than hide it.

## Scripts

Add or update scripts so the workflow can be reproduced from the repository
root:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_strategy_comparison_report.py --include-dqn
PYTHONPATH=src .venv/bin/python scripts/run_factor_diagnostics_report.py
PYTHONPATH=src .venv/bin/python scripts/build_research_dashboard.py
```

The exact CLI can include additional defaults, but each command must write its
artifact under `outputs/`.

## Testing

Use test-driven implementation. Required tests:

- DQN config decays epsilon to its floor.
- DQN trainer returns a strategy that can produce a valid buy/sell/hold
  decision.
- Strategy comparison report includes `dqn_v1` and DQN diagnostics.
- Factor library exposes default factor specs and skips missing columns safely.
- Factor diagnostics computes Rank IC without requiring SciPy.
- Factor report includes metadata and warnings.
- Dashboard generation writes HTML containing strategy and factor sections.

Verification command:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
```

## Success Criteria

- PyTorch is installed in `.venv` and importable.
- All tests pass with `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`.
- Strategy comparison report includes `dqn_v1`.
- Factor diagnostics report exists under `outputs/`.
- Research dashboard HTML exists under `outputs/` and can be opened locally.
- Existing Q-learning behavior remains available for comparison.
