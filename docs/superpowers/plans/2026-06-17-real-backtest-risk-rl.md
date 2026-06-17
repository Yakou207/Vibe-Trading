# Real Backtest, Risk Gate, and RL Training Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify a daily A-share backtest engine with risk controls, a real baseline strategy run, a Gymnasium-compatible RL environment, and an initial training script.

**Architecture:** Strategy decisions flow through a risk gate into a portfolio executor that owns cash, positions, costs, T+1 sellability, and equity snapshots. The RL environment reuses the portfolio and cost semantics so baseline and RL rewards are comparable.

**Tech Stack:** Python 3.14, pandas, unittest, optional gymnasium.

## Global Constraints

- Keep the system daily-frequency and A-share focused.
- Use local AkShare feature data as the primary research input.
- Do not add live brokerage integration.
- Do not add high-frequency matching.
- Keep changes surgical and tied to the research-system goal.
- Write tests before production code and verify they fail before implementation.

---

### Task 1: Portfolio, Costs, and Risk Gate

**Files:**
- Create: `src/fintech_quant/backtesting/costs.py`
- Create: `src/fintech_quant/backtesting/portfolio.py`
- Modify: `src/fintech_quant/risk/rules.py`
- Test: `tests/test_backtesting_portfolio.py`

**Interfaces:**
- Produces: `CostModel`, `Order`, `Trade`, `Position`, `PortfolioSnapshot`, `Portfolio`, `RiskDecision`, `RiskGate`.
- Consumes: existing `RiskLimits`.

- [ ] Write failing tests for cost deduction, lot rounding, T+1 blocking, max weight blocking, and drawdown blocking.
- [ ] Run `PYTHONPATH=src python3 -m unittest tests.test_backtesting_portfolio -v` and verify failures are missing imports/classes.
- [ ] Implement minimal portfolio, cost, and risk classes.
- [ ] Re-run the focused test and verify it passes.

### Task 2: Backtest Engine and Baseline Adapter

**Files:**
- Create: `src/fintech_quant/backtesting/engine.py`
- Modify: `src/fintech_quant/strategies/buy_and_hold.py`
- Test: `tests/test_backtesting_engine.py`

**Interfaces:**
- Consumes: `Portfolio`, `RiskGate`, `CostModel`, `TradeAction`.
- Produces: `BacktestConfig`, `BacktestMetrics`, `BacktestResult`, `run_daily_backtest`, `EqualWeightBuyAndHoldStrategy`.

- [ ] Write failing tests proving a tiny feature frame produces trades, snapshots, and non-zero metrics.
- [ ] Run `PYTHONPATH=src python3 -m unittest tests.test_backtesting_engine -v` and verify failures are missing imports/classes.
- [ ] Implement the engine and baseline adapter.
- [ ] Re-run the focused test and verify it passes.

### Task 3: Baseline Backtest CLI and Docs

**Files:**
- Create: `scripts/run_backtest_baseline.py`
- Modify: `README.md`
- Test: `tests/test_backtest_baseline_script.py`

**Interfaces:**
- Consumes: `run_daily_backtest`, `EqualWeightBuyAndHoldStrategy`.
- Produces: `outputs/baseline_backtest.json`.

- [ ] Write a failing CLI test using a temporary feature CSV and output path.
- [ ] Run `PYTHONPATH=src python3 -m unittest tests.test_backtest_baseline_script -v` and verify failure.
- [ ] Implement the script and README command.
- [ ] Re-run the focused test and verify it passes.

### Task 4: Gymnasium-Compatible RL Environment

**Files:**
- Modify: `src/fintech_quant/training/rl_environment.py`
- Test: `tests/test_rl_environment.py`

**Interfaces:**
- Consumes: `Portfolio`, `CostModel`, feature columns from `features.indicators`.
- Produces: `AShareBuySellHoldEnvironment.reset()` and `.step(action)`.

- [ ] Write failing tests for reset, buy step, hold step, done state, and reward.
- [ ] Run `PYTHONPATH=src python3 -m unittest tests.test_rl_environment -v` and verify failure.
- [ ] Implement the environment with optional Gymnasium spaces when installed.
- [ ] Re-run the focused test and verify it passes.

### Task 5: Initial RL Training Script

**Files:**
- Create: `scripts/train_rl_random_policy.py`
- Modify: `README.md`
- Test: `tests/test_rl_training_script.py`

**Interfaces:**
- Consumes: `AShareBuySellHoldEnvironment`.
- Produces: `outputs/rl_random_policy_training.json`.

- [ ] Write a failing script test using a temporary feature CSV and deterministic seed.
- [ ] Run `PYTHONPATH=src python3 -m unittest tests.test_rl_training_script -v` and verify failure.
- [ ] Implement the random-policy training loop and README command.
- [ ] Re-run the focused test and verify it passes.

### Task 6: Full Verification

**Files:**
- All files changed above.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: verified working research loop.

- [ ] Run `PYTHONPATH=src python3 -m unittest discover -s tests`.
- [ ] Run `PYTHONPATH=src python3 scripts/run_backtest_baseline.py`.
- [ ] Run `PYTHONPATH=src python3 scripts/train_rl_random_policy.py --episodes 3`.
- [ ] Inspect both JSON outputs for required metrics.

