# Phase 3 Data Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic A-share selected-universe daily data and feature pipeline for baseline and future DQN research.

**Architecture:** Keep provider collection separate from indicator generation. Use pure standard-library functions for indicators and CSV persistence so tests are deterministic and do not require network access.

**Tech Stack:** Python 3.14, standard library `csv`, `json`, `datetime`, existing `unittest` suite.

## Global Constraints

- Do not add pandas or other hard runtime dependencies in this phase.
- Do not modify DQN training.
- Do not hit AkShare/Tushare in tests.
- Keep outputs under ignored `data/processed/` unless explicitly committed as fixtures.
- Preserve the existing Phase 1 and Phase 2 public APIs.

---

### Task 1: Technical Indicator Generation

**Files:**
- Create: `src/fintech_quant/features/technical_indicators.py`
- Modify: `src/fintech_quant/features/__init__.py`
- Test: `tests/test_technical_indicators.py`

**Interfaces:**
- Produces: `enrich_daily_bars(rows, ma_windows=(20, 60, 250), rsi_period=14, volatility_window=20) -> list[dict[str, object]]`

### Task 2: Research Dataset CSV And Provider Collection

**Files:**
- Create: `src/fintech_quant/data/research_dataset.py`
- Modify: `src/fintech_quant/data/__init__.py`
- Test: `tests/test_research_dataset.py`

**Interfaces:**
- Produces: `UniverseMember`
- Produces: `load_universe_csv(path: Path) -> list[UniverseMember]`
- Produces: `collect_universe_history(provider, universe, start, end) -> list[dict[str, object]]`
- Produces: `write_daily_bars_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None`
- Produces: `write_feature_rows_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None`

### Task 3: Refresh Script And Documentation

**Files:**
- Create: `scripts/refresh_research_data.py`
- Modify: `README.md`
- Modify: `docs/phase-one-change-report.md`
- Test: `tests/test_refresh_research_data_script.py`

**Interfaces:**
- CLI supports fixture mode:
  - `--source json`
  - `--input fixture.json`
  - `--universe universe.csv`
  - `--daily-output daily.csv`
  - `--feature-output features.csv`
- CLI supports provider mode:
  - `--source auto`
  - `--start YYYY-MM-DD`
  - `--end YYYY-MM-DD`
  - `--universe universe.csv`
  - `--daily-output daily.csv`
  - `--feature-output features.csv`

## Verification

Run after each task:

```bash
PYTHONPATH=/Users/yakou/Desktop/Vibe-Trading/.worktrees/phase3-data-pipeline/src \
  /Users/yakou/Desktop/Vibe-Trading/.venv/bin/python -m unittest discover -s tests
```

Expected: all tests pass.
