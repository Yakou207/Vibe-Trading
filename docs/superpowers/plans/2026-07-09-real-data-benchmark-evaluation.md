# Real-Data Benchmark Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a real-data main-path strategy baseline and benchmark-relative evaluation for the existing 30-stock STAR Market universe.

**Architecture:** Keep raw data immutable and write real-run generated artifacts to dated output paths. Extend the existing performance comparison module to treat index CSVs as benchmark net-value curves. Port DQN checkpoint/resume support into the current torch DQN path without reviving q-learning as a strategy path.

**Tech Stack:** Python 3, unittest/pytest, AkShare CSV/index data, existing `fintech_quant` package modules, optional PyTorch for DQN.

## Global Constraints

- Use the real baseline window `2021-06-16` through `2026-06-16`.
- Use `data/processed/akshare_research_universe.csv` as the selected 30-stock universe.
- Do not overwrite raw AkShare data files.
- Keep strategy logic unchanged before producing the real-data baseline.
- Do not reintroduce q-learning as an active strategy path.
- Write tests before production code for behavior changes.

---

### Task 1: Add Benchmark-Relative Comparison Metrics

**Files:**
- Modify: `tests/test_performance_comparison.py`
- Modify: `src/fintech_quant/reports/performance.py`
- Modify: `scripts/compare_strategy_reports.py`

**Interfaces:**
- Consumes: existing `compare_strategy_reports(baseline_report, candidate_report, ...)`.
- Produces: optional benchmark support through `benchmark_curves: Mapping[str, Sequence[Mapping[str, object]]] | None`.
- Produces: JSON fields `benchmarks`, `baseline_vs_benchmark`, `candidate_vs_benchmark`.

- [ ] **Step 1: Write failing benchmark comparison tests**

Add tests that create a benchmark curve with `trade_date` and `index_close`, call `compare_strategy_reports(..., benchmark_curves={"sse": benchmark})`, and assert:

```python
self.assertAlmostEqual(comparison.benchmarks["sse"].total_return, 0.02)
self.assertAlmostEqual(comparison.candidate_vs_benchmark["sse"]["excess_return"], 0.06)
self.assertIn("tracking_max_drawdown", comparison.candidate_vs_benchmark["sse"])
self.assertIn("candidate_benchmark_excess_return", comparison.walk_forward[0])
```

Also add a script test that passes:

```bash
python3 scripts/compare_strategy_reports.py \
  --baseline baseline.json \
  --candidate candidate.json \
  --benchmark sse=index.csv \
  --output comparison.json
```

Expected JSON contains `benchmarks.sse`, `candidate_vs_benchmark.sse.excess_return`, and `tracking_max_drawdown`.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_performance_comparison.py -q
```

Expected: FAIL because `benchmark_curves` and `--benchmark` are not implemented.

- [ ] **Step 3: Implement benchmark parsing and metrics**

In `src/fintech_quant/reports/performance.py`:

- Add a benchmark summary dataclass or reuse a summary type with `name`, `initial_equity`, `ending_equity`, `total_return`, and `max_drawdown`.
- Add `_benchmark_curve(rows)` that accepts `trade_date` plus `index_close`, `close`, or `equity`, sorts by date, and converts the series into net value starting at `1.0`.
- Add `_align_curve_to_dates(curve, dates)` that keeps only strategy dates and raises if any strategy date is missing.
- Add `_tracking_max_drawdown(strategy_curve, benchmark_curve)` using the drawdown of `strategy_net_value / benchmark_net_value`.
- Extend `_walk_forward` to include benchmark segment return and baseline/candidate benchmark excess returns when benchmark data is present.

In `scripts/compare_strategy_reports.py`:

- Add repeatable `--benchmark name=path`.
- Load CSV benchmark files through `csv.DictReader`.
- Pass parsed benchmark rows into `compare_strategy_reports`.
- Print benchmark-relative candidate excess return lines for quick CLI inspection.

- [ ] **Step 4: Run targeted tests to verify green**

Run:

```bash
python3 -m pytest tests/test_performance_comparison.py -q
```

Expected: PASS.

---

### Task 2: Port Resumable Torch DQN Checkpoints

**Files:**
- Modify: `tests/test_torch_dqn_training.py`
- Create: `src/fintech_quant/training/dqn_checkpoint.py`
- Modify: `src/fintech_quant/training/torch_dqn.py`
- Modify: `src/fintech_quant/training/__init__.py`

**Interfaces:**
- Consumes: current `TorchDQNPolicy`, `TorchDQNConfig`, `train_torch_dqn_policy`.
- Produces: `TorchDQNTrainingRun`, `train_torch_dqn_policy_run`, `save_torch_dqn_checkpoint`, `load_torch_dqn_checkpoint`, `load_latest_torch_dqn_checkpoint`.

- [ ] **Step 1: Write failing checkpoint tests**

Add a test that trains a tiny torch DQN run when torch is installed:

```python
run = train_torch_dqn_policy_run(samples, TorchDQNConfig(episodes=1, batch_size=1))
checkpoint = save_torch_dqn_checkpoint(run, root, checkpoint_id="unit")
loaded = load_torch_dqn_checkpoint(checkpoint)
resumed = train_torch_dqn_policy_run(samples, TorchDQNConfig(episodes=1, batch_size=1), initial_run=loaded)
self.assertEqual(resumed.episodes_trained, loaded.episodes_trained + 1)
self.assertGreaterEqual(resumed.policy.training_steps, loaded.policy.training_steps)
```

If torch is missing, assert the existing clean `RuntimeError` behavior remains.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_torch_dqn_training.py -q
```

Expected: FAIL because checkpoint APIs do not exist.

- [ ] **Step 3: Implement minimal checkpoint support**

In `torch_dqn.py`:

- Add `TorchDQNTrainingRun` with `policy`, `target_network`, `optimizer_state`, `replay`, `episodes_trained`, `metadata`, and `metrics`.
- Add `train_torch_dqn_policy_run(samples, config=None, initial_run=None)` and make `train_torch_dqn_policy` return `train_torch_dqn_policy_run(...).policy`.
- When `initial_run` is supplied, reuse scaler, network, target network, replay, optimizer state, and continue exploration from `episodes_trained`.

In `dqn_checkpoint.py`:

- Save `model.pt`, `target_model.pt`, `optimizer.pt`, `replay_buffer.pkl`, `scaler.json`, `config.json`, `training_state.json`, `metrics.json`, and `manifest.json`.
- Load those files back into a `TorchDQNTrainingRun`.
- Keep only torch DQN names in public APIs.

- [ ] **Step 4: Run targeted tests to verify green**

Run:

```bash
python3 -m pytest tests/test_torch_dqn_training.py tests/test_dqn_walk_forward.py -q
```

Expected: PASS or documented skip when torch is unavailable.

---

### Task 3: Run Real-Data Main Chain and Benchmark Reports

**Files:**
- Generated: `data/processed/real_main_20260616_daily.csv`
- Generated: `data/processed/real_main_20260616_features.csv`
- Generated: `data/processed/real_main_20260616_rl_state_dataset.jsonl`
- Generated: `data/raw/market_state/sh000001_20210616_20260616.csv`
- Generated: `data/raw/market_state/sh000300_20210616_20260616.csv`
- Generated: `outputs/research_runs/real_main_20260616/run_report.json`
- Generated: `outputs/research_runs/real_main_20260616_dqn_policy/run_report.json`
- Generated: `outputs/research_runs/real_main_20260616_dqn_walk_forward/report.json`
- Generated: `outputs/research_runs/real_main_20260616/baseline_vs_dqn_benchmarks.json`

**Interfaces:**
- Consumes: current scripts and real local AkShare raw files/provider access.
- Produces: real-data baseline, DQN walk-forward report, and benchmark-relative comparison JSON.

- [ ] **Step 1: Run relevant unit tests before real data**

Run:

```bash
python3 -m pytest tests/test_performance_comparison.py tests/test_torch_dqn_training.py tests/test_dqn_walk_forward.py -q
```

Expected: PASS or torch-specific skips only when torch is unavailable.

- [ ] **Step 2: Fetch benchmark index state**

Run:

```bash
python3 scripts/fetch_market_state.py --source akshare --index-symbol sh000001 --start 2021-06-16 --end 2026-06-16 --output data/raw/market_state/sh000001_20210616_20260616.csv --ma-window 250
python3 scripts/fetch_market_state.py --source akshare --index-symbol sh000300 --start 2021-06-16 --end 2026-06-16 --output data/raw/market_state/sh000300_20210616_20260616.csv --ma-window 250
```

Expected: both commands print positive `stored_market_state_rows`.

- [ ] **Step 3: Run daily research pipeline into run-specific outputs**

Run:

```bash
python3 scripts/run_daily_research_pipeline.py \
  --universe data/processed/akshare_research_universe.csv \
  --start 2021-06-16 \
  --end 2026-06-16 \
  --price-source akshare \
  --information-source akshare_multi \
  --market-source akshare \
  --information-output data/raw/information/real_main_20260616_information.jsonl \
  --classified-information-output-dir data/raw/information/real_main_20260616_classified \
  --information-summary-output outputs/real_main_20260616_information_summary.json \
  --daily-output data/processed/real_main_20260616_daily.csv \
  --feature-output data/processed/real_main_20260616_features.csv \
  --market-output data/raw/market_state/sh000001_20210616_20260616.csv \
  --rl-output data/processed/real_main_20260616_rl_state_dataset.jsonl \
  --dqn-policy-report-output outputs/research_runs/real_main_20260616_dqn_policy/run_report.json \
  --dqn-eval-start 2024-06-16 \
  --dqn-policy-transaction-cost 0.001 \
  --dqn-drawdown-penalty 0.5 \
  --scoring-coverage-output outputs/real_main_20260616_scoring_coverage.json \
  --stock-analysis-output outputs/real_main_20260616_stock_analysis.json \
  --run-id real_main_20260616 \
  --report-output-root outputs/research_runs \
  --index-symbol sh000001
```

Expected: generated daily/features/RL/report paths exist and row counts are materially larger than fixture counts.

- [ ] **Step 4: Run DQN walk-forward**

Run:

```bash
python3 scripts/run_dqn_walk_forward.py \
  --input data/processed/real_main_20260616_rl_state_dataset.jsonl \
  --output outputs/research_runs/real_main_20260616_dqn_walk_forward/report.json \
  --train-years 2 \
  --eval-years 1 \
  --episodes 5 \
  --transaction-cost 0.001 \
  --drawdown-penalty 0.5 \
  --run-id real_main_20260616_torch_dqn_walk_forward
```

Expected: report prints positive `window_count`.

- [ ] **Step 5: Produce benchmark-relative comparison**

The DQN walk-forward report is a rolling validation report, not a single equity report. Compare the baseline against the daily-pipeline DQN policy report, and keep the walk-forward report as separate out-of-sample evidence.

Run the comparison command with both benchmarks:

```bash
python3 scripts/compare_strategy_reports.py \
  --baseline outputs/research_runs/real_main_20260616/run_report.json \
  --candidate outputs/research_runs/real_main_20260616_dqn_policy/run_report.json \
  --benchmark sse=data/raw/market_state/sh000001_20210616_20260616.csv \
  --benchmark csi300=data/raw/market_state/sh000300_20210616_20260616.csv \
  --output outputs/research_runs/real_main_20260616/baseline_vs_dqn_benchmarks.json \
  --align-to-candidate
```

Expected: comparison JSON contains benchmark-relative metrics for both `sse` and `csi300`.

- [ ] **Step 6: Summarize evidence**

Run a short row-count and metric inspection command:

```bash
python3 - <<'PY'
import csv, json
from pathlib import Path
for path in [
    "data/processed/real_main_20260616_daily.csv",
    "data/processed/real_main_20260616_features.csv",
    "data/processed/real_main_20260616_rl_state_dataset.jsonl",
]:
    p = Path(path)
    if p.suffix == ".jsonl":
        print(path, sum(1 for line in p.open(encoding="utf-8") if line.strip()))
    else:
        with p.open(encoding="utf-8", newline="") as handle:
            print(path, sum(1 for _ in csv.DictReader(handle)))
comparison = Path("outputs/research_runs/real_main_20260616/baseline_vs_dqn_benchmarks.json")
if comparison.exists():
    payload = json.loads(comparison.read_text(encoding="utf-8"))
    print(json.dumps({
        "excess_return": payload.get("excess_return"),
        "candidate_vs_benchmark": payload.get("candidate_vs_benchmark"),
    }, ensure_ascii=False, indent=2, sort_keys=True))
PY
```

Expected: row counts and benchmark-relative metrics are printed.
