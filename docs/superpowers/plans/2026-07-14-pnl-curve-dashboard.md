# PnL Curve Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a source-backed, interactive three-series cumulative PnL line chart to the accepted HFQ CSI 300 dashboard without changing trading behavior.

**Architecture:** A focused report module extracts the small top-level `equity_curve` arrays from the two large formal reports without loading the reports into memory, aligns them with the CSI 300 CSV, and writes a compact hash-bearing `pnl_curve.json`. The existing HTML dashboard embeds validated curve data and renders it with pinned Chart.js 4.5.1; the post-close V2 evidence manifest hash-binds the optional reporting input.

**Tech Stack:** Python 3.14 standard library, unittest/pytest, HTML/CSS/JavaScript, Chart.js 4.5.1 UMD from pinned jsDelivr URL.

## Global Constraints

- Use only accepted HFQ formal artifacts; never use the rejected incremental-QFQ run.
- Normalize all three series to CNY 100,000 on the first shared trading date.
- Keep all daily points; do not downsample, interpolate, forward-fill, or truncate.
- Curve data stays local and embedded; only the pinned Chart.js renderer may use the network.
- Missing, malformed, non-finite, duplicate-date, or misaligned source data fails closed.
- The curve is reporting-only and cannot affect targets, fills, account NAV, drawdown state, or readiness calculations.
- Preserve V2 atomic output and hash-chain behavior.
- Use test-first red-green cycles and make only request-traceable changes.

---

### Task 1: Build the compact PnL curve artifact

**Files:**
- Create: `src/fintech_quant/reports/pnl_curve.py`
- Create: `scripts/build_pnl_curve.py`
- Create: `tests/test_pnl_curve_report.py`

**Interfaces:**
- Produces: `build_pnl_curve(*, baseline_report: Path, risk_controlled_report: Path, benchmark: Path, initial_equity: float = 100000.0) -> dict[str, object]`
- Produces: `validate_pnl_curve(payload: Mapping[str, object]) -> None`
- Produces: `write_pnl_curve(path: Path, payload: Mapping[str, object]) -> None`
- CLI: `scripts/build_pnl_curve.py --baseline-report BASELINE --risk-controlled-report RISK --benchmark BENCHMARK --output OUTPUT`

- [ ] **Step 1: Write normalization and provenance tests**

```python
def test_build_pnl_curve_normalizes_three_aligned_series(tmp_path: Path) -> None:
    baseline = _write_report(tmp_path / "baseline.json", [("2026-01-02", 200.0), ("2026-01-05", 220.0)])
    risk = _write_report(tmp_path / "risk.json", [("2026-01-02", 400.0), ("2026-01-05", 460.0)])
    benchmark = tmp_path / "benchmark.csv"
    benchmark.write_text("trade_date,index_close\n2026-01-02,1000\n2026-01-05,1050\n", encoding="utf-8")

    payload = build_pnl_curve(
        baseline_report=baseline,
        risk_controlled_report=risk,
        benchmark=benchmark,
    )

    assert payload["dates"] == ["2026-01-02", "2026-01-05"]
    assert payload["series"]["baseline"]["equity"] == [100000.0, 110000.0]
    assert payload["series"]["risk_controlled"]["pnl"] == [0.0, 15000.0]
    assert payload["series"]["csi300"]["return"] == [0.0, 0.05]
    assert payload["inputs"]["baseline_report"]["sha256"] == hashlib.sha256(baseline.read_bytes()).hexdigest()
```

- [ ] **Step 2: Run the test and verify RED**

Run: `.venv/bin/python -m pytest tests/test_pnl_curve_report.py -q`

Expected: collection fails because `fintech_quant.reports.pnl_curve` does not exist.

- [ ] **Step 3: Implement the minimum artifact builder**

Implement a read-only `mmap` extractor that finds the top-level `"equity_curve"` array and decodes only that bounded array. Parse each `{trade_date, equity}` point, require strict ascending unique ISO dates and finite positive initial values, read `index_close`, `close`, or `equity` from the benchmark CSV, and require every strategy date. Generate aligned `dates`, `equity`, `pnl`, and `return` arrays with equity/PnL rounded to 6 decimals and returns to 10 decimals. Record resolved path, byte count, and SHA-256 for all three inputs.

- [ ] **Step 4: Run normalization test and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_pnl_curve_report.py::test_build_pnl_curve_normalizes_three_aligned_series -q`

Expected: `1 passed`.

- [ ] **Step 5: Add fail-closed and CLI tests**

```python
@pytest.mark.parametrize("case", ["date_mismatch", "duplicate_date", "missing_benchmark", "non_finite", "zero_initial"])
def test_build_pnl_curve_rejects_invalid_inputs(tmp_path: Path, case: str) -> None:
    baseline, risk, benchmark = _invalid_case(tmp_path, case)
    with pytest.raises(ValueError):
        build_pnl_curve(baseline_report=baseline, risk_controlled_report=risk, benchmark=benchmark)

def test_build_pnl_curve_cli_writes_valid_deterministic_json(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_pnl_curve.py",
            "--baseline-report", str(baseline),
            "--risk-controlled-report", str(risk),
            "--benchmark", str(benchmark),
            "--output", str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    validate_pnl_curve(payload)
    first = output.read_bytes()
    subprocess.run(completed.args, cwd=ROOT, check=True)
    assert output.read_bytes() == first
```

- [ ] **Step 6: Run fail-closed tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_pnl_curve_report.py -q`

Expected: failures identify missing validation, writer, or CLI behavior.

- [ ] **Step 7: Implement validation, deterministic writer, and CLI**

`validate_pnl_curve` must require schema version 1, initial equity 100000, non-empty increasing dates, exactly the `risk_controlled`, `baseline`, and `csi300` series, matching array lengths, finite numeric values, and internal `equity - initial == pnl` / `pnl / initial == return` consistency within the chosen rounding tolerance. The CLI calls the builder, validates the result, writes sorted indented JSON plus one newline, and prints `pnl_curve_path=<path>`.

- [ ] **Step 8: Run Task 1 tests and commit**

Run: `.venv/bin/python -m pytest tests/test_pnl_curve_report.py -q`

Expected: all tests pass.

```bash
git add src/fintech_quant/reports/pnl_curve.py scripts/build_pnl_curve.py tests/test_pnl_curve_report.py
git commit -m "feat: build auditable PnL curve artifact"
```

---

### Task 2: Render the interactive chart in the existing dashboard

**Files:**
- Modify: `src/fintech_quant/reports/dashboard.py`
- Modify: `scripts/build_research_dashboard.py`
- Modify: `tests/test_research_dashboard_report.py`

**Interfaces:**
- Consumes: validated mapping from `load_json(Path(args.pnl_curve))`
- Changes: `build_research_dashboard(*, comparison: Mapping[str, object], walk_forward: Mapping[str, object] | None = None, paper_report: Mapping[str, object] | None = None, run_report: Mapping[str, object] | None = None, data_health: Mapping[str, object] | None = None, information_health: Mapping[str, object] | None = None, pnl_curve: Mapping[str, object] | None = None) -> str`
- CLI: adds optional `--pnl-curve`

- [ ] **Step 1: Write chart and fallback tests**

```python
def test_dashboard_embeds_interactive_pnl_curve(tmp_path: Path) -> None:
    completed, html = _build_dashboard(tmp_path, pnl_curve=_valid_curve())
    assert completed.returncode == 0
    assert "https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js" in html
    assert 'id="pnl-chart"' in html
    assert 'id="pnl-curve-data"' in html
    assert "Risk-Controlled" in html and "Baseline" in html and "CSI 300" in html
    assert "Normalized Cumulative PnL" in html
    assert "normalized equity" in html.lower()

def test_dashboard_shows_pnl_fallback_without_curve(tmp_path: Path) -> None:
    _, html = _build_dashboard(tmp_path, pnl_curve=None)
    assert "PnL curve unavailable" in html
    assert "chart.umd.min.js" not in html
```

- [ ] **Step 2: Run chart tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_research_dashboard_report.py -q`

Expected: new chart assertions fail because the CLI and HTML do not support PnL data.

- [ ] **Step 3: Implement the chart section**

Add `--pnl-curve` to the dashboard CLI and pass its JSON mapping to `build_research_dashboard`. Validate the optional payload with `validate_pnl_curve`. For valid data, embed escaped JSON in `<script type="application/json" id="pnl-curve-data">`, load the pinned UMD renderer, and create one responsive line chart after KPI cards and before the benchmark table. Use teal solid for risk-controlled, blue dashed for baseline, amber dotted for CSI 300; no persistent point markers; a visible zero gridline; CNY Y-axis ticks; auto-skipped dates; and tooltip rows for PnL, normalized equity, and cumulative return. For missing/malformed data, show a non-chart fallback card. If `window.Chart` is unavailable, replace the canvas with `Chart renderer unavailable` while preserving the rest of the dashboard.

- [ ] **Step 4: Run dashboard tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_research_dashboard_report.py -q`

Expected: all dashboard tests pass.

- [ ] **Step 5: Run focused regression and commit**

Run: `.venv/bin/python -m pytest tests/test_research_dashboard_report.py tests/test_pnl_curve_report.py -q`

Expected: all focused tests pass.

```bash
git add src/fintech_quant/reports/dashboard.py scripts/build_research_dashboard.py tests/test_research_dashboard_report.py
git commit -m "feat: add interactive PnL chart to dashboard"
```

---

### Task 3: Bind the reporting input into V2 paper evidence

**Files:**
- Modify: `scripts/run_post_close_daily_cycle.py`
- Modify: `tests/test_run_post_close_daily_cycle_script.py`

**Interfaces:**
- CLI: adds optional `--pnl-curve`
- V2 manifest: adds `inputs.pnl_curve` only when supplied
- Replay: verifies the supplied curve reference matches the manifest and still passes its recorded path/size/hash checks

- [ ] **Step 1: Write V2 propagation and replay tests**

```python
def test_v2_cycle_hash_binds_pnl_curve(self) -> None:
    paths = _write_v2_inputs(root)
    paths["pnl_curve"].write_text(json.dumps(_valid_curve()), encoding="utf-8")
    completed = _run_v2_cycle(paths, pnl_curve=paths["pnl_curve"])
    manifest = json.loads(paths["cycle_manifest"].read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert manifest["inputs"]["pnl_curve"]["sha256"] == hashlib.sha256(paths["pnl_curve"].read_bytes()).hexdigest()
    assert "pnl-chart" in paths["dashboard"].read_text(encoding="utf-8")

def test_v2_replay_rejects_changed_pnl_curve(self) -> None:
    first = _run_v2_cycle(paths, pnl_curve=paths["pnl_curve"])
    assert first.returncode == 0
    paths["pnl_curve"].write_text("{}\n", encoding="utf-8")
    replay = _run_v2_cycle(paths, pnl_curve=paths["pnl_curve"])
    assert replay.returncode != 0
    assert "pnl_curve" in replay.stderr or "artifact hash mismatch" in replay.stderr
```

- [ ] **Step 2: Run V2 tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_run_post_close_daily_cycle_script.py -q`

Expected: helper/CLI assertions fail because `--pnl-curve` is unknown and the manifest lacks the input.

- [ ] **Step 3: Implement optional propagation and replay validation**

Add `--pnl-curve`, append it to `build_research_dashboard.py` only when supplied, and include it in V2 `input_paths`. Change `_validate_completed_cycle` to receive the current optional PnL path; when the manifest has a PnL reference, verify the referenced file and require its resolved path/size/hash to equal `file_reference(current_path)`. Reject supplying a PnL curve when the completed manifest did not bind one, and reject omitting one when it did.

- [ ] **Step 4: Run V2 tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_run_post_close_daily_cycle_script.py -q`

Expected: all cycle tests pass.

- [ ] **Step 5: Run focused integration regression and commit**

Run: `.venv/bin/python -m pytest tests/test_run_post_close_daily_cycle_script.py tests/test_research_dashboard_report.py tests/test_pnl_curve_report.py -q`

Expected: all focused tests pass.

```bash
git add scripts/run_post_close_daily_cycle.py tests/test_run_post_close_daily_cycle_script.py
git commit -m "feat: bind PnL chart data into paper evidence"
```

---

### Task 4: Wire CSI 300 discovery and regenerate the authoritative dashboard

**Files:**
- Modify: `scripts/run_csi300_post_close.py`
- Modify: `tests/test_run_csi300_post_close_script.py`
- Generate: `outputs/csi300_research/hfq-formal-20260713/pnl_curve.json` (ignored run artifact)
- Generate: `outputs/paper_trading/csi300_baseline/hfq_formal_dashboard.html` (ignored run artifact)

**Interfaces:**
- Changes: `PipelineConfig` adds `pnl_curve: Path | None = None`
- CLI: adds optional `--pnl-curve`
- Default: when no explicit path is supplied, use `pnl_curve.json` beside `comparison` if it exists; otherwise preserve the visible dashboard fallback

- [ ] **Step 1: Write explicit and sibling-discovery tests**

```python
def test_pipeline_passes_sibling_pnl_curve_to_paper_cycle(self) -> None:
    curve = config.comparison.with_name("pnl_curve.json")
    _write_json(curve, _valid_curve())
    run_pipeline(config, runner=runner)
    paper_command = next(command for command, _ in runner.calls if Path(command[0]).name == "run_post_close_daily_cycle.py")
    assert _argument(paper_command, "--pnl-curve") == str(curve)
```

Also test that an explicit missing path fails before provider calls and that absence of a sibling leaves `--pnl-curve` out of the command.

- [ ] **Step 2: Run CSI wrapper tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_run_csi300_post_close_script.py -q`

Expected: the new configuration/command assertions fail.

- [ ] **Step 3: Implement explicit path and sibling discovery**

Parse `--pnl-curve`, resolve it before pipeline stages, fail if an explicit path is missing, otherwise discover the sibling artifact. Append `--pnl-curve <path>` to the paper-cycle command only when a file is available. Do not add it to decision-report, target, execution, or validation-audit commands.

- [ ] **Step 4: Run CSI wrapper tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_run_csi300_post_close_script.py -q`

Expected: all CSI wrapper tests pass.

- [ ] **Step 5: Generate the accepted HFQ curve artifact**

Run:

```bash
.venv/bin/python scripts/build_pnl_curve.py \
  --baseline-report /Users/yakou/Desktop/Vibe-Trading/outputs/csi300_research/hfq-formal-20260713/baseline/run_report.json \
  --risk-controlled-report /Users/yakou/Desktop/Vibe-Trading/outputs/csi300_research/hfq-formal-20260713/risk_controlled/run_report.json \
  --benchmark /Users/yakou/Desktop/Vibe-Trading/data/diagnostics/csi300_market_state_sina_20200601_20260713.csv \
  --output /Users/yakou/Desktop/Vibe-Trading/outputs/csi300_research/hfq-formal-20260713/pnl_curve.json
```

Expected: stdout equals `pnl_curve_path=/Users/yakou/Desktop/Vibe-Trading/outputs/csi300_research/hfq-formal-20260713/pnl_curve.json`; validation confirms three series and matching final returns.

- [ ] **Step 6: Regenerate the accepted local Dashboard**

Run:

```bash
.venv/bin/python scripts/build_research_dashboard.py \
  --comparison /Users/yakou/Desktop/Vibe-Trading/outputs/csi300_research/hfq-formal-20260713/benchmark_comparison.json \
  --paper-report /Users/yakou/Desktop/Vibe-Trading/outputs/paper_trading/csi300_baseline/report_2026-07-13.json \
  --pnl-curve /Users/yakou/Desktop/Vibe-Trading/outputs/csi300_research/hfq-formal-20260713/pnl_curve.json \
  --output /Users/yakou/Desktop/Vibe-Trading/outputs/paper_trading/csi300_baseline/hfq_formal_dashboard.html
```

Expected: output contains the chart canvas, embedded daily curve, and the accepted headline metrics without the rejected QFQ values.

- [ ] **Step 7: Run full verification**

Run:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src scripts tests
git diff --check
```

Expected: all tests pass, compilation exits 0, and diff check is empty.

Validate the generated curve against `benchmark_comparison.json`: final normalized returns equal the baseline, candidate, and CSI 300 totals within rounding tolerance; maximum risk-controlled drawdown remains a metric from the accepted report rather than a recomputed chart claim. Inspect the final HTML structurally and refresh the already-open local file for visual QA at desktop width.

- [ ] **Step 8: Review scope, commit, and push**

Review every changed line against the design, confirm no trading code path consumes PnL values, and verify `git status` contains only intended source, tests, and docs.

```bash
git add scripts/run_csi300_post_close.py tests/test_run_csi300_post_close_script.py docs/superpowers/plans/2026-07-14-pnl-curve-dashboard.md
git commit -m "feat: wire CSI300 PnL dashboard artifact"
git push origin codex/pnl-curve-dashboard
```
