# Optimization Log

## 2026-06-18

### Problems Addressed

- Created a Git backup branch and tag before modifying the project.
- Added a repeatable `make test` command for the `src/` layout.
- Declared dashboard dependencies and a console entrypoint in `pyproject.toml`.
- Replaced the AkShare placeholder with a usable daily history adapter.
- Added reusable equity-curve metrics for return, Sharpe ratio, and max drawdown.
- Added a dashboard data model that reads local research artifacts.
- Added a local Streamlit dashboard for strategy comparison, baseline PnL/equity,
  data quality, and factor diagnostics.
- Expanded `scripts/check_env.py` from a version print into a structured project
  environment check.

### Remaining Research-System Work

- Move the scripts that produced current `outputs/*.json` into tracked code.
- Export per-strategy equity curves so the dashboard can plot PnL lines for
  RSI/MACD, Q-learning, DQN, and buy-and-hold side by side.
- Add formal A-share execution constraints to the backtest engine: T+1, lot size,
  suspension, limit-up/limit-down, fees, tax, and slippage.
- Keep walk-forward training and testing separation mandatory for future RL work.

## 2026-06-18 Dashboard UX Pass

### Problems Addressed

- Reworked the dashboard into a research cockpit with Overview, PnL, Strategy
  Lab, Factors, and Data Ops tabs.
- Added an explicit reload action for local research artifacts.
- Added a strategy recommendation helper that prioritizes risk-adjusted
  performance instead of raw return alone.
- Replaced deprecated Streamlit `use_container_width` calls with the current
  `width="stretch"` API.
- Introduced `DashboardConfig` and `DashboardDataSource` so future non-daily
  data, paper-trading feeds, and model-versioned result bundles can plug into
  the same dashboard UI.
- Fixed dashboard process management during verification by replacing the stale
  Streamlit process that was still listening on port 8501.
