# Phase 4 Research Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible daily A-share research run that turns local feature, information, fundamental, and capital-flow inputs into scores, risk warnings, a multi-symbol baseline backtest, and `run_report.json`.

**Architecture:** Add a focused `fintech_quant.research` package for offline data loading, score assembly, risk assembly, and run report orchestration. Add a separate multi-symbol portfolio baseline runner under `fintech_quant.backtesting` so the existing one-symbol runner remains stable. Keep all logic rule-based and inspectable.

**Tech Stack:** Python standard library only, existing dataclasses, `unittest`, CSV/JSON/JSONL files, existing `ScoreInput`, `score_stock`, `RiskInput`, `evaluate_risk`, and drawdown engine.

## Global Constraints

- Daily A-share research first.
- Local deterministic files first; network fetch remains in earlier refresh scripts.
- One command should produce a reproducible run report.
- Prefer transparent rule-based mappings over opaque models.
- Keep model training out of Phase 4.
- No live brokerage integration.
- No Web UI, MCP server, Hermes interface, external NLP model, minute-level data, or parameter optimization.
- The portfolio baseline must enforce 100-share lots and default max position weight of 8%.
- Risk exits must be triggerable by the 15% portfolio drawdown rule.
- Tests must run offline.

---

## File Structure

- Create `src/fintech_quant/research/__init__.py`
  - Export Phase 4 research-run interfaces.
- Create `src/fintech_quant/research/dataset.py`
  - Load and validate feature, fundamental, capital-flow, market-state, and information files.
- Create `src/fintech_quant/research/scoring.py`
  - Convert merged rows and information records into `ScoreInput` and `StockScore`.
- Create `src/fintech_quant/research/risk_builder.py`
  - Build `RiskInput` rows from portfolio/position state plus optional risk fields.
- Create `src/fintech_quant/research/run.py`
  - Orchestrate dataset loading, scoring, baseline run, and report serialization.
- Create `src/fintech_quant/backtesting/portfolio_research_runner.py`
  - Multi-symbol baseline runner with simple A-share constraints.
- Modify `src/fintech_quant/backtesting/__init__.py`
  - Export portfolio runner types.
- Create `scripts/run_research_baseline.py`
  - CLI entry point.
- Create tests:
  - `tests/test_research_dataset_phase4.py`
  - `tests/test_research_scoring.py`
  - `tests/test_research_risk_builder.py`
  - `tests/test_portfolio_research_runner.py`
  - `tests/test_run_research_baseline_script.py`

---

### Task 1: Phase 4 Research Dataset Loader

**Files:**
- Create: `src/fintech_quant/research/__init__.py`
- Create: `src/fintech_quant/research/dataset.py`
- Test: `tests/test_research_dataset_phase4.py`

**Interfaces:**
- Produces:
  - `FeatureRow(symbol: str, trade_date: date, values: dict[str, object])`
  - `SupplementalRow(symbol: str, trade_date: date | None, values: dict[str, object])`
  - `MarketStateRow(trade_date: date, values: dict[str, object])`
  - `ResearchDataset(features, fundamentals, capital_flow, market_state, information_records, universe_symbols)`
  - `load_research_dataset(features_path, universe_path, fundamentals_path=None, capital_flow_path=None, market_state_path=None, information_path=None) -> ResearchDataset`

- [ ] **Step 1: Write failing dataset loader tests**

```python
def test_load_research_dataset_normalizes_sorts_and_filters_universe(self):
    dataset = load_research_dataset(features_path, universe_path)
    self.assertEqual([(row.trade_date.isoformat(), row.symbol) for row in dataset.features], [
        ("2026-01-01", "000001.SZ"),
        ("2026-01-02", "000001.SZ"),
    ])
```

```python
def test_load_research_dataset_rejects_duplicate_feature_rows(self):
    with self.assertRaisesRegex(ValueError, "Duplicate feature row"):
        load_research_dataset(features_path, universe_path)
```

```python
def test_load_research_dataset_loads_optional_supplemental_files(self):
    dataset = load_research_dataset(
        features_path,
        universe_path,
        fundamentals_path=fundamentals_path,
        capital_flow_path=capital_flow_path,
        market_state_path=market_state_path,
        information_path=information_path,
    )
    self.assertEqual(dataset.fundamentals[("000001.SZ", None)].values["pe"], 18.0)
    self.assertEqual(dataset.capital_flow[("000001.SZ", date(2026, 1, 2))].values["main_outflow_days"], 4)
    self.assertEqual(dataset.market_state[date(2026, 1, 2)].values["index_below_annual_ma"], True)
    self.assertEqual(dataset.information_records[0].title, "Risk notice")
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONPATH=/Users/yakou/Desktop/Vibe-Trading/.worktrees/phase4-research-run/src \
  /Users/yakou/Desktop/Vibe-Trading/.venv/bin/python -m unittest tests.test_research_dataset_phase4
```

Expected: fail because `fintech_quant.research.dataset` does not exist.

- [ ] **Step 3: Implement minimal dataset loader**

Implementation notes:

- Use `csv.DictReader`.
- Use existing `load_universe_csv` and `normalize_a_share_symbol`.
- Required feature columns are the Phase 3 feature schema.
- Convert blank optional values to `None`.
- Convert known boolean strings: `"true"`, `"1"`, `"yes"` -> `True`; `"false"`, `"0"`, `"no"` -> `False`.
- Convert numeric strings to `float` or `int` only in known numeric fields.
- Filter feature and supplemental rows to universe symbols.
- Reject duplicate feature keys `(symbol, trade_date)`.

- [ ] **Step 4: Run tests and commit**

Run:

```bash
PYTHONPATH=/Users/yakou/Desktop/Vibe-Trading/.worktrees/phase4-research-run/src \
  /Users/yakou/Desktop/Vibe-Trading/.venv/bin/python -m unittest tests.test_research_dataset_phase4
```

Commit:

```bash
git add src/fintech_quant/research/__init__.py src/fintech_quant/research/dataset.py tests/test_research_dataset_phase4.py
git commit -m "feat: add phase four research dataset loader"
```

---

### Task 2: Score And Risk Builders

**Files:**
- Create: `src/fintech_quant/research/scoring.py`
- Create: `src/fintech_quant/research/risk_builder.py`
- Modify: `src/fintech_quant/research/__init__.py`
- Test: `tests/test_research_scoring.py`
- Test: `tests/test_research_risk_builder.py`

**Interfaces:**
- Consumes: `ResearchDataset`, `FeatureRow`, `SupplementalRow`, `MarketStateRow`
- Produces:
  - `build_score_input(feature_row, fundamentals=None, capital_flow=None, information_records=()) -> ScoreInput`
  - `build_stock_scores(dataset: ResearchDataset) -> dict[tuple[date, str], StockScore]`
  - `PositionState(shares: int = 0, cost_basis: float = 0.0, market_value: float = 0.0)`
  - `PortfolioRiskState(equity: float, rolling_peak: float, positions: dict[str, PositionState])`
  - `build_risk_input(symbol, trade_date, close, portfolio_state, fundamentals=None, capital_flow=None, market_state=None, information_records=()) -> RiskInput`

- [ ] **Step 1: Write failing scoring tests**

```python
def test_build_score_input_maps_feature_fundamental_capital_and_information(self):
    score_input = build_score_input(feature_row, fundamentals, capital_flow, [negative_record])
    self.assertEqual(score_input.symbol, "000001.SZ")
    self.assertEqual(score_input.pe, 18.0)
    self.assertEqual(score_input.close_above_ma20, True)
    self.assertEqual(score_input.rsi, 55.0)
    self.assertEqual(score_input.main_outflow_days, 4)
    self.assertEqual(score_input.negative_event_count, 1)
```

```python
def test_build_stock_scores_preserves_35_25_25_15_pipeline(self):
    scores = build_stock_scores(dataset)
    score = scores[(date(2026, 1, 1), "000001.SZ")]
    self.assertIn("fundamental", score.components)
    self.assertIn("technical", score.components)
    self.assertIn("capital_flow", score.components)
    self.assertIn("sentiment", score.components)
```

- [ ] **Step 2: Write failing risk builder tests**

```python
def test_build_risk_input_uses_portfolio_drawdown_and_single_position_drawdown(self):
    risk_input = build_risk_input(
        "000001.SZ",
        date(2026, 1, 2),
        8.0,
        PortfolioRiskState(
            equity=85000.0,
            rolling_peak=100000.0,
            positions={"000001.SZ": PositionState(shares=1000, cost_basis=10.0, market_value=8000.0)},
        ),
    )
    self.assertEqual(risk_input.portfolio_drawdown, 0.15)
    self.assertEqual(risk_input.single_position_drawdown, 0.2)
```

```python
def test_build_risk_input_maps_fundamental_capital_market_and_information(self):
    risk_input = build_risk_input(
        "000001.SZ",
        date(2026, 1, 2),
        10.0,
        portfolio_state,
        fundamentals={"st_warning": True, "goodwill_ratio": 0.35, "pledge_ratio": 0.6},
        capital_flow={"main_outflow_days": 4},
        market_state={"index_below_annual_ma": True, "broad_market_drop_gt_3pct_count": 16},
        information_records=[negative_record],
    )
    self.assertTrue(risk_input.st_warning)
    self.assertEqual(risk_input.goodwill_ratio, 0.35)
    self.assertEqual(risk_input.main_outflow_days, 4)
    self.assertTrue(risk_input.index_below_annual_ma)
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
PYTHONPATH=/Users/yakou/Desktop/Vibe-Trading/.worktrees/phase4-research-run/src \
  /Users/yakou/Desktop/Vibe-Trading/.venv/bin/python -m unittest tests.test_research_scoring tests.test_research_risk_builder
```

Expected: fail because modules do not exist.

- [ ] **Step 4: Implement builders**

Implementation notes:

- `volume_confirmed`: `volume > 0 and return_1d is not None and return_1d >= 0`.
- `negative_event_count`: count same-symbol information records with `published_at <= trade_date` and risk tag in `NEGATIVE_RISK_TAGS`.
- `limit_up_streak` and `dragon_tiger_positive` stay missing unless source fields exist.
- `PortfolioRiskState.rolling_peak` must be positive to compute drawdown; otherwise drawdown is `0.0`.
- Round drawdowns to 6 decimals.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
PYTHONPATH=/Users/yakou/Desktop/Vibe-Trading/.worktrees/phase4-research-run/src \
  /Users/yakou/Desktop/Vibe-Trading/.venv/bin/python -m unittest tests.test_research_scoring tests.test_research_risk_builder
```

Commit:

```bash
git add src/fintech_quant/research/__init__.py src/fintech_quant/research/scoring.py src/fintech_quant/research/risk_builder.py tests/test_research_scoring.py tests/test_research_risk_builder.py
git commit -m "feat: build research scores and risk inputs"
```

---

### Task 3: Multi-Symbol Portfolio Baseline Runner

**Files:**
- Create: `src/fintech_quant/backtesting/portfolio_research_runner.py`
- Modify: `src/fintech_quant/backtesting/__init__.py`
- Test: `tests/test_portfolio_research_runner.py`

**Interfaces:**
- Consumes:
  - `bars: Sequence[Mapping[str, object]]`
  - `scores: Mapping[tuple[date, str], StockScore]`
  - `risk_inputs: Mapping[tuple[date, str], RiskInput] | None`
- Produces:
  - `PortfolioBacktestTrade`
  - `PortfolioDailyEquity`
  - `PortfolioBacktestResult`
  - `run_portfolio_scored_baseline_backtest(...) -> PortfolioBacktestResult`

- [ ] **Step 1: Write failing portfolio runner tests**

```python
def test_portfolio_runner_buys_100_share_lots_with_position_cap(self):
    result = run_portfolio_scored_baseline_backtest(bars, scores, initial_cash=100000.0)
    buy = result.trades[0]
    self.assertEqual(buy.action, TradeAction.BUY)
    self.assertEqual(buy.shares % 100, 0)
    self.assertLessEqual(buy.notional, 8000.0)
```

```python
def test_portfolio_runner_blocks_same_day_sell_after_buy(self):
    result = run_portfolio_scored_baseline_backtest(bars, scores, risk_inputs=risk_inputs)
    same_day_actions = [(trade.trade_date, trade.action) for trade in result.trades]
    self.assertNotIn((date(2026, 1, 1), TradeAction.SELL), same_day_actions)
```

```python
def test_portfolio_runner_liquidates_on_portfolio_drawdown_risk(self):
    result = run_portfolio_scored_baseline_backtest(bars, scores, risk_inputs=risk_inputs)
    self.assertEqual(result.trades[-1].action, TradeAction.SELL)
    self.assertEqual(result.risk_warnings[-1].rule, "portfolio_drawdown")
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
PYTHONPATH=/Users/yakou/Desktop/Vibe-Trading/.worktrees/phase4-research-run/src \
  /Users/yakou/Desktop/Vibe-Trading/.venv/bin/python -m unittest tests.test_portfolio_research_runner
```

Expected: fail because portfolio runner does not exist.

- [ ] **Step 3: Implement portfolio runner**

Implementation notes:

- Group bars by `trade_date`, then sort symbols inside each date.
- Mark-to-market all open positions using current date closes.
- Use `ScoredBaselineStrategy` for buy/hold/sell intent.
- Position target cash is `initial_equity * max_position_weight` by default.
- Shares are rounded down to nearest `lot_size=100`.
- Buy price includes slippage: `close * (1 + slippage_rate)`.
- Sell price includes slippage: `close * (1 - slippage_rate)`.
- Commission is `notional * commission_rate`.
- Do not sell a symbol on the same date it was bought.
- Summary includes `initial_cash`, `ending_equity`, `total_return`, `max_drawdown`, `trade_count`, `risk_warning_count`, `turnover`, and `win_rate`.

- [ ] **Step 4: Run tests and commit**

Run:

```bash
PYTHONPATH=/Users/yakou/Desktop/Vibe-Trading/.worktrees/phase4-research-run/src \
  /Users/yakou/Desktop/Vibe-Trading/.venv/bin/python -m unittest tests.test_portfolio_research_runner
```

Commit:

```bash
git add src/fintech_quant/backtesting/__init__.py src/fintech_quant/backtesting/portfolio_research_runner.py tests/test_portfolio_research_runner.py
git commit -m "feat: add portfolio scored baseline runner"
```

---

### Task 4: Research Run Orchestrator

**Files:**
- Create: `src/fintech_quant/research/run.py`
- Modify: `src/fintech_quant/research/__init__.py`
- Test: `tests/test_research_run.py`

**Interfaces:**
- Consumes:
  - `ResearchDataset`
  - `run_portfolio_scored_baseline_backtest`
- Produces:
  - `ResearchRunConfig`
  - `ResearchRunReport`
  - `run_research_baseline(config: ResearchRunConfig) -> ResearchRunReport`
  - `write_run_report(report: ResearchRunReport, output_dir: Path) -> Path`

- [ ] **Step 1: Write failing orchestrator tests**

```python
def test_run_research_baseline_outputs_scores_risks_trades_equity_and_summary(self):
    report = run_research_baseline(config)
    self.assertEqual(report.run_id, "fixture-run")
    self.assertGreater(len(report.scores), 0)
    self.assertGreater(len(report.trades), 0)
    self.assertGreater(len(report.equity_curve), 0)
    self.assertIn("max_drawdown", report.summary)
```

```python
def test_write_run_report_serializes_stable_json(self):
    path = write_run_report(report, output_dir)
    payload = json.loads(path.read_text(encoding="utf-8"))
    self.assertEqual(payload["run_id"], "fixture-run")
    self.assertIn("scores", payload)
    self.assertIn("risk_warnings", payload)
    self.assertIn("summary", payload)
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
PYTHONPATH=/Users/yakou/Desktop/Vibe-Trading/.worktrees/phase4-research-run/src \
  /Users/yakou/Desktop/Vibe-Trading/.venv/bin/python -m unittest tests.test_research_run
```

Expected: fail because `fintech_quant.research.run` does not exist.

- [ ] **Step 3: Implement orchestrator**

Implementation notes:

- Convert feature rows to bars for the portfolio runner.
- Build `scores` using `build_stock_scores`.
- Build risk inputs date-by-date using current portfolio state when available.
- For the first implementation, risk inputs from supplemental files can be built before the runner using neutral portfolio state; the portfolio runner still enforces explicit risk inputs and drawdown liquidation.
- Serialize dataclasses manually into JSON-safe dictionaries.
- Sort report arrays by date and symbol for stable output.

- [ ] **Step 4: Run tests and commit**

Run:

```bash
PYTHONPATH=/Users/yakou/Desktop/Vibe-Trading/.worktrees/phase4-research-run/src \
  /Users/yakou/Desktop/Vibe-Trading/.venv/bin/python -m unittest tests.test_research_run
```

Commit:

```bash
git add src/fintech_quant/research/__init__.py src/fintech_quant/research/run.py tests/test_research_run.py
git commit -m "feat: orchestrate phase four research run"
```

---

### Task 5: CLI And Documentation

**Files:**
- Create: `scripts/run_research_baseline.py`
- Modify: `README.md`
- Modify: `docs/phase-one-change-report.md`
- Test: `tests/test_run_research_baseline_script.py`

**Interfaces:**
- Consumes:
  - `ResearchRunConfig`
  - `run_research_baseline`
  - `write_run_report`
- Produces:
  - CLI command that writes `outputs/research_runs/<run_id>/run_report.json`

- [ ] **Step 1: Write failing CLI test**

```python
def test_run_research_baseline_script_writes_report_from_offline_fixtures(self):
    result = subprocess.run([...], cwd=worktree, env=env, capture_output=True, text=True, check=False)
    self.assertEqual(result.returncode, 0, msg=result.stderr)
    self.assertIn("report_path=", result.stdout)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    self.assertEqual(payload["run_id"], "fixture-run")
    self.assertIn("summary", payload)
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
PYTHONPATH=/Users/yakou/Desktop/Vibe-Trading/.worktrees/phase4-research-run/src \
  /Users/yakou/Desktop/Vibe-Trading/.venv/bin/python -m unittest tests.test_run_research_baseline_script
```

Expected: fail because script does not exist.

- [ ] **Step 3: Implement CLI**

Arguments:

```text
--run-id
--features
--universe
--information
--fundamentals
--capital-flow
--market-state
--output-root
--initial-cash
--max-position-weight
--commission-rate
--slippage-rate
```

Defaults:

- `--output-root outputs/research_runs`
- `--initial-cash 100000`
- `--max-position-weight 0.08`
- `--commission-rate 0.0003`
- `--slippage-rate 0.0005`

- [ ] **Step 4: Update docs**

README Phase 4 section should show:

```bash
python scripts/run_research_baseline.py \
  --run-id fixture-run \
  --features data/processed/akshare_research_features.csv \
  --universe universe.csv \
  --output-root outputs/research_runs
```

Change report should state Phase 4 adds reproducible research run reports and keeps DQN frozen until baseline comparison artifacts exist.

- [ ] **Step 5: Run full test suite and commit**

Run:

```bash
PYTHONPATH=/Users/yakou/Desktop/Vibe-Trading/.worktrees/phase4-research-run/src \
  /Users/yakou/Desktop/Vibe-Trading/.venv/bin/python -m unittest discover -s tests
```

Commit:

```bash
git add scripts/run_research_baseline.py README.md docs/phase-one-change-report.md tests/test_run_research_baseline_script.py
git commit -m "feat: add phase four research baseline CLI"
```

---

## Final Verification

- [ ] Run all tests:

```bash
PYTHONPATH=/Users/yakou/Desktop/Vibe-Trading/.worktrees/phase4-research-run/src \
  /Users/yakou/Desktop/Vibe-Trading/.venv/bin/python -m unittest discover -s tests
```

- [ ] Run `git diff --check`.
- [ ] Request whole-branch code review.
- [ ] Fix any Critical or Important review findings.
- [ ] Push `codex/phase4-research-run`.
- [ ] Merge to `main`.
- [ ] Re-run full tests on `main`.
- [ ] Push `main` to GitHub.

