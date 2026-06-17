# PyTorch DQN Factor Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a PyTorch DQN strategy, factor diagnostics report, and local research dashboard for the A-share daily research system.

**Architecture:** Keep the existing backtest engine as the strategy evaluation boundary. Add DQN as a new `Strategy` adapter beside Q-learning, add factor metadata beside existing feature diagnostics, and render a static HTML dashboard from bounded local JSON outputs.

**Tech Stack:** Python 3.14, pandas, numpy, PyTorch, unittest, static HTML/CSS.

## Global Constraints

- Work against `data/processed/akshare_research_features.csv` as the primary source.
- Keep Q-learning available as a visible comparison baseline.
- Do not add brokerage integration, intraday data, new external data providers, NLP training, or broad hyperparameter search.
- Use PyTorch CPU-compatible training in the current `.venv`.
- Avoid SciPy for Spearman Rank IC by ranking with pandas and using Pearson correlation.
- Verify with `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`.

---

### Task 1: PyTorch Dependency And DQN Core

**Files:**
- Modify: `pyproject.toml`
- Create: `src/fintech_quant/training/dqn.py`
- Test: `tests/test_dqn.py`

**Interfaces:**
- Consumes: `TradeAction`, `TradeDecision`, `Strategy`, existing numeric feature columns.
- Produces: `DQNConfig`, `DQNModel`, `DQNStrategy`, `train_dqn(frame, config=None)`.

- [ ] **Step 1: Install PyTorch**

Run:

```bash
.venv/bin/python -m pip install torch
```

Expected: command exits 0 and `.venv/bin/python -c "import torch; print(torch.__version__)"` prints a version.

- [ ] **Step 2: Write failing DQN tests**

Create `tests/test_dqn.py` with tests for epsilon decay and valid strategy decisions:

```python
from __future__ import annotations

import unittest

import pandas as pd


class DQNTest(unittest.TestCase):
    def test_dqn_config_decays_epsilon_to_floor(self) -> None:
        from fintech_quant.training.dqn import DQNConfig

        config = DQNConfig(epsilon=0.8, min_epsilon=0.1, epsilon_decay=0.5)

        self.assertAlmostEqual(config.exploration_rate(0), 0.8)
        self.assertAlmostEqual(config.exploration_rate(1), 0.4)
        self.assertAlmostEqual(config.exploration_rate(4), 0.1)

    def test_dqn_strategy_returns_trade_decision(self) -> None:
        from fintech_quant.training.dqn import DQNConfig, DQNStrategy, train_dqn
        from fintech_quant.trading import TradeAction

        frame = pd.DataFrame(
            {
                "代码": ["sh688001", "sh688001", "sh688001", "sh688001"],
                "date": ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
                "close": [10.0, 10.5, 11.0, 10.8],
                "rsi_14": [45.0, 55.0, 65.0, 50.0],
                "macd_hist": [0.1, 0.2, 0.1, -0.1],
                "return_5d": [0.01, 0.02, 0.03, -0.01],
                "return_20d": [0.01, 0.02, 0.03, -0.01],
                "close_to_ma_20": [1.0, 1.01, 1.02, 0.99],
                "ma_20_slope": [0.01, 0.01, 0.02, 0.0],
                "volatility_20": [0.02, 0.02, 0.03, 0.03],
                "target_next_return_1d": [0.05, 0.04, -0.02, 0.0],
            }
        )

        model = train_dqn(frame, DQNConfig(episodes=1, batch_size=2, seed=1))
        strategy = DQNStrategy(model=model, target_weight=0.25)

        decision = strategy.decide({**frame.iloc[0].to_dict(), "position_quantity": 0})

        self.assertIn(decision.action, {TradeAction.HOLD, TradeAction.BUY, TradeAction.SELL})
        self.assertIn("DQN", decision.reason)
```

- [ ] **Step 3: Run tests to verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_dqn
```

Expected: FAIL because `fintech_quant.training.dqn` does not exist.

- [ ] **Step 4: Implement minimal DQN core**

Add:

- `DQNConfig` dataclass with epsilon decay.
- `FeatureScaler` for mean/std normalization.
- `DQNNetwork` small MLP.
- replay memory and training loop.
- `DQNModel.predict_action()`.
- `DQNStrategy.decide()`.

- [ ] **Step 5: Verify DQN tests pass**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_dqn
```

Expected: PASS.

---

### Task 2: Factor Library And SciPy-Free Rank IC

**Files:**
- Create: `src/fintech_quant/features/factor_library.py`
- Modify: `src/fintech_quant/features/factor_diagnostics.py`
- Modify: `src/fintech_quant/reports/factor_report.py`
- Test: `tests/test_factor_library.py`
- Modify: `tests/test_analysis_framework_contracts.py`

**Interfaces:**
- Consumes: feature tables with numeric factor columns and `target_next_return_1d`.
- Produces: `FactorSpec`, `default_factor_specs()`, `available_factor_specs(features)`, enriched factor diagnostics.

- [ ] **Step 1: Write failing tests**

Add tests that assert default factor metadata exists, missing columns are skipped, Rank IC works without SciPy, and factor report includes metadata.

- [ ] **Step 2: Run factor tests to verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_factor_library tests.test_analysis_framework_contracts
```

Expected: FAIL because `factor_library.py` does not exist and Rank IC still calls pandas Spearman.

- [ ] **Step 3: Implement factor library and diagnostics**

Add factor specs for momentum, trend, risk, volume, and oscillator factors. Change Rank IC to:

```python
rank_ic = _safe_corr(data[column].rank(), data[target_column].rank(), method="pearson")
```

Enrich each factor metric with `group`, `description`, and `direction`.

- [ ] **Step 4: Verify factor tests pass**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_factor_library tests.test_analysis_framework_contracts
```

Expected: PASS.

---

### Task 3: Strategy Comparison With DQN

**Files:**
- Modify: `src/fintech_quant/reports/strategy_comparison.py`
- Modify: `scripts/run_strategy_comparison_report.py`
- Test: `tests/test_strategy_comparison_report.py`
- Test: `tests/test_strategy_comparison_script.py`

**Interfaces:**
- Consumes: `train_dqn`, `DQNConfig`, `DQNStrategy`.
- Produces: strategy comparison payload containing `dqn_v1`, `dqn`, and `dqn_diagnostics`.

- [ ] **Step 1: Write failing tests**

Update strategy comparison tests to expect `dqn_v1` in `window["strategies"]`, `dqn_v1_vs_equal_weight_buy_and_hold` in excess returns, and `dqn_diagnostics` in each window.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_strategy_comparison_report tests.test_strategy_comparison_script
```

Expected: FAIL because `dqn_v1` is not present.

- [ ] **Step 3: Add DQN to comparison report**

Train DQN per walk-forward train window, add `DQNStrategy` to the strategy map, and produce diagnostics with decision action counts and configured feature columns.

- [ ] **Step 4: Verify comparison tests pass**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_strategy_comparison_report tests.test_strategy_comparison_script
```

Expected: PASS.

---

### Task 4: Factor Report And Dashboard Scripts

**Files:**
- Create: `scripts/run_factor_diagnostics_report.py`
- Create: `src/fintech_quant/reports/research_dashboard.py`
- Create: `scripts/build_research_dashboard.py`
- Test: `tests/test_factor_diagnostics_script.py`
- Test: `tests/test_research_dashboard.py`

**Interfaces:**
- Consumes: local CSV and JSON outputs.
- Produces: `outputs/factor_diagnostics_report.json` and `outputs/research_dashboard.html`.

- [ ] **Step 1: Write failing tests**

Add script tests that run in a temp directory and assert JSON/HTML files are written with expected top-level sections.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_factor_diagnostics_script tests.test_research_dashboard
```

Expected: FAIL because scripts and dashboard module do not exist.

- [ ] **Step 3: Implement scripts and dashboard renderer**

Render static HTML with sections for data coverage, strategy comparison, DQN diagnostics, and factor diagnostics. Escape user/data strings with `html.escape`.

- [ ] **Step 4: Verify dashboard tests pass**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_factor_diagnostics_script tests.test_research_dashboard
```

Expected: PASS.

---

### Task 5: Full Verification And Artifact Generation

**Files:**
- Modify: `README.md`
- Generated: `outputs/strategy_comparison_report.json`
- Generated: `outputs/factor_diagnostics_report.json`
- Generated: `outputs/research_dashboard.html`

**Interfaces:**
- Consumes: all implemented scripts.
- Produces: updated docs and fresh local artifacts.

- [ ] **Step 1: Update README commands**

Document PyTorch DQN, factor diagnostics, and dashboard commands.

- [ ] **Step 2: Run full test suite**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
```

Expected: PASS.

- [ ] **Step 3: Generate reports**

Run:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_strategy_comparison_report.py
PYTHONPATH=src .venv/bin/python scripts/run_factor_diagnostics_report.py
PYTHONPATH=src .venv/bin/python scripts/build_research_dashboard.py
```

Expected: commands exit 0 and write outputs under `outputs/`.

- [ ] **Step 4: Inspect git diff**

Run:

```bash
git status --short
git diff --stat
```

Expected: only planned files changed.
