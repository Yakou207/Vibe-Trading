# Q-Learning RL v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a simple tabular Q-learning strategy, evaluate it with walk-forward train/test splits, and output an RL vs buy-and-hold report using the real backtest engine.

**Architecture:** The learner fits train-only state bins and a Q-table, then exposes a `QLearningStrategy` through the existing strategy interface. A report runner trains per walk-forward window and backtests RL and buy-and-hold on the same test rows with the existing cost/risk engine.

**Tech Stack:** Python 3.14, pandas, unittest, existing backtesting and walk-forward modules.

## Global Constraints

- Use simple Q-learning, not DQN/PPO.
- Train only on walk-forward train windows.
- Fit state bins only from train data.
- Evaluate RL and buy-and-hold on identical test windows using the real backtest engine.
- Avoid look-ahead bias.
- Keep a strategy interface that can later be replaced by DQN.
- Write tests before production code.

---

### Task 1: State Binning

**Files:**
- Create: `src/fintech_quant/training/q_learning.py`
- Test: `tests/test_q_learning.py`

**Interfaces:**
- Produces: `StateBinner.fit(frame: pd.DataFrame) -> StateBinner`, `StateBinner.transform_row(row: Mapping[str, object], position_flag: int) -> tuple[str, str, str, str, int]`.

- [ ] Write failing tests for train-only quantile fitting and row transformation.
- [ ] Run `PYTHONPATH=src python3 -m unittest tests.test_q_learning -v` and verify import/class failures.
- [ ] Implement `StateBinner`.
- [ ] Re-run the focused test and verify it passes.

### Task 2: Q-Learning Trainer and Strategy

**Files:**
- Modify: `src/fintech_quant/training/q_learning.py`
- Test: `tests/test_q_learning.py`

**Interfaces:**
- Produces: `QLearningConfig`, `QLearningModel`, `train_q_learning(frame: pd.DataFrame, config: QLearningConfig) -> QLearningModel`, `QLearningStrategy`.
- Consumes: `TradeAction`, `TradeDecision`, `StateBinner`.

- [ ] Write failing tests showing a Q-value update and strategy action selection.
- [ ] Run `PYTHONPATH=src python3 -m unittest tests.test_q_learning -v` and verify failures.
- [ ] Implement config, model, trainer, and strategy adapter.
- [ ] Re-run the focused test and verify it passes.

### Task 3: Walk-Forward RL vs Baseline Report

**Files:**
- Create: `src/fintech_quant/reports/rl_vs_baseline.py`
- Test: `tests/test_rl_vs_baseline_report.py`

**Interfaces:**
- Produces: `run_q_learning_walk_forward_report(features: pd.DataFrame, config: QLearningConfig) -> dict[str, object]`.
- Consumes: `rolling_windows`, `slice_window`, `run_daily_backtest`, `EqualWeightBuyAndHoldStrategy`, `QLearningStrategy`.

- [ ] Write failing tests proving report windows contain train/test dates, RL metrics, buy-and-hold metrics, and excess return.
- [ ] Run `PYTHONPATH=src python3 -m unittest tests.test_rl_vs_baseline_report -v` and verify failures.
- [ ] Implement report builder using identical test data for both strategies.
- [ ] Re-run the focused test and verify it passes.

### Task 4: CLI and README

**Files:**
- Create: `scripts/run_walk_forward_q_learning.py`
- Modify: `README.md`
- Test: `tests/test_q_learning_script.py`

**Interfaces:**
- Consumes: `run_q_learning_walk_forward_report`.
- Produces: `outputs/rl_vs_buy_hold_report.json`.

- [ ] Write a failing CLI test with a temporary feature CSV and output path.
- [ ] Run `PYTHONPATH=src python3 -m unittest tests.test_q_learning_script -v` and verify failure.
- [ ] Implement CLI arguments and README command.
- [ ] Re-run the focused test and verify it passes.

### Task 5: Verification and Backup

**Files:**
- All changed files.

**Interfaces:**
- Produces: tested and pushed branch.

- [ ] Run `PYTHONPATH=src python3 -m unittest discover -s tests`.
- [ ] Run `PYTHONPATH=src python3 scripts/run_walk_forward_q_learning.py`.
- [ ] Inspect `outputs/rl_vs_buy_hold_report.json` for window-level RL and baseline metrics.
- [ ] Commit changes.
- [ ] Push `codex/q-learning-rl-v1` to GitHub.

