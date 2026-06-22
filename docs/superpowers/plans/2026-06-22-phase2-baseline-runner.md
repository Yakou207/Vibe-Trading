# Phase 2 Baseline Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic one-symbol daily backtest runner for the scored baseline strategy.

**Architecture:** Add one focused orchestration module under `backtesting`. The runner consumes normalized bars, precomputed scores, and optional risk inputs, then delegates strategy, risk, and drawdown work to existing modules.

**Tech Stack:** Python dataclasses, standard library `datetime`, existing `unittest` test suite.

## Global Constraints

- Keep this as a research backtest, not a live broker.
- Do not change DQN training in this phase.
- Do not fetch network data inside the runner.
- Use simple all-in/all-out accounting with no fees, slippage, T+1, or lot-size constraints.
- Preserve the existing Phase 1 APIs unless a test proves a narrow extension is required.

---

### Task 1: Research Backtest Runner

**Files:**
- Create: `src/fintech_quant/backtesting/research_runner.py`
- Modify: `src/fintech_quant/backtesting/__init__.py`
- Test: `tests/test_research_backtest_runner.py`

**Interfaces:**
- Consumes: `ScoredBaselineStrategy.decide(state)`, `evaluate_risk(RiskInput)`, `calculate_drawdown(points)`, `StockScore`, `RiskInput`, `RiskWarning`.
- Produces:
  - `BacktestTrade`
  - `DailyEquity`
  - `DatedRiskWarning`
  - `ResearchBacktestResult`
  - `run_scored_baseline_backtest(...)`

- [ ] **Step 1: Write failing tests**

Create `tests/test_research_backtest_runner.py` with tests that:

```python
from datetime import date
import unittest

from fintech_quant.backtesting import run_scored_baseline_backtest
from fintech_quant.features import ComponentScore, StockScore
from fintech_quant.risk import RiskInput
from fintech_quant.trading import TradeAction


def make_score(symbol: str, total: float) -> StockScore:
    return StockScore(
        symbol=symbol,
        total=total,
        components={
            "fundamental": ComponentScore("fundamental", total, 35.0, ()),
            "technical": ComponentScore("technical", 0.0, 25.0, ()),
            "capital": ComponentScore("capital", 0.0, 25.0, ()),
            "sentiment": ComponentScore("sentiment", 0.0, 15.0, ()),
        },
        confidence=1.0,
        missing_fields=(),
    )


class ResearchBacktestRunnerTest(unittest.TestCase):
    def test_baseline_runner_buys_holds_and_sells_on_risk(self) -> None:
        bars = [
            {"symbol": "000001.SZ", "trade_date": "2026-01-01", "close": 10.0},
            {"symbol": "000001.SZ", "trade_date": "2026-01-02", "close": 12.0},
            {"symbol": "000001.SZ", "trade_date": "2026-01-03", "close": 9.0},
        ]
        scores = {
            date(2026, 1, 1): make_score("000001.SZ", 80.0),
            date(2026, 1, 2): make_score("000001.SZ", 80.0),
            date(2026, 1, 3): make_score("000001.SZ", 80.0),
        }
        risk_inputs = {
            date(2026, 1, 3): RiskInput(portfolio_drawdown=0.15),
        }

        result = run_scored_baseline_backtest(
            bars,
            scores,
            risk_inputs=risk_inputs,
            initial_cash=1000.0,
        )

        self.assertEqual([trade.action for trade in result.trades], [TradeAction.BUY, TradeAction.SELL])
        self.assertEqual(result.trades[0].shares, 100)
        self.assertEqual(result.trades[1].shares, 100)
        self.assertEqual([point.equity for point in result.equity_curve], [1000.0, 1200.0, 900.0])
        self.assertAlmostEqual(result.drawdown.max_drawdown, 0.25)
        self.assertEqual(result.summary["ending_equity"], 900.0)
        self.assertEqual(result.summary["total_return"], -0.10)
        self.assertEqual(result.summary["trade_count"], 2)
        self.assertEqual(result.risk_warnings[0].rule, "portfolio_drawdown")

    def test_baseline_runner_requires_score_for_each_bar_date(self) -> None:
        bars = [{"symbol": "000001.SZ", "trade_date": "2026-01-01", "close": 10.0}]

        with self.assertRaisesRegex(ValueError, "Missing score"):
            run_scored_baseline_backtest(bars, {}, initial_cash=1000.0)
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
PYTHONPATH=/Users/yakou/Desktop/Vibe-Trading/.worktrees/phase2-baseline-runner/src \
  /Users/yakou/Desktop/Vibe-Trading/.venv/bin/python -m unittest tests.test_research_backtest_runner
```

Expected: import failure because `run_scored_baseline_backtest` is not exported yet.

- [ ] **Step 3: Implement minimal runner**

Create `research_runner.py` with dataclasses and `run_scored_baseline_backtest`. Export it from `backtesting/__init__.py`. Keep accounting simple and deterministic.

- [ ] **Step 4: Run focused and full tests**

Run:

```bash
PYTHONPATH=/Users/yakou/Desktop/Vibe-Trading/.worktrees/phase2-baseline-runner/src \
  /Users/yakou/Desktop/Vibe-Trading/.venv/bin/python -m unittest tests.test_research_backtest_runner
PYTHONPATH=/Users/yakou/Desktop/Vibe-Trading/.worktrees/phase2-baseline-runner/src \
  /Users/yakou/Desktop/Vibe-Trading/.venv/bin/python -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/fintech_quant/backtesting/research_runner.py src/fintech_quant/backtesting/__init__.py tests/test_research_backtest_runner.py
git commit -m "feat: add scored baseline research runner"
```

### Task 2: Documentation And Change Report

**Files:**
- Modify: `README.md`
- Modify: `docs/phase-one-change-report.md`

**Interfaces:**
- Consumes: Task 1 runner API.
- Produces: human-readable project status and next-step guidance.

- [ ] **Step 1: Document Phase 2 runner**

Add a short README note that the project has a deterministic scored baseline backtest runner for DQN comparison.

- [ ] **Step 2: Update change report**

Append a Phase 2 section with:

- runner scope
- simplifications
- test command
- remaining gaps

- [ ] **Step 3: Run full tests**

Run:

```bash
PYTHONPATH=/Users/yakou/Desktop/Vibe-Trading/.worktrees/phase2-baseline-runner/src \
  /Users/yakou/Desktop/Vibe-Trading/.venv/bin/python -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/phase-one-change-report.md docs/superpowers/specs/2026-06-22-phase2-baseline-runner-design.md docs/superpowers/plans/2026-06-22-phase2-baseline-runner.md
git commit -m "docs: describe phase two baseline runner"
```
