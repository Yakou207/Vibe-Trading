# CSI 300 Post-Close Cycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one deterministic, incremental, fail-closed CSI 300 post-close command that commits a paper account exactly once only after fresh data and every validation gate pass.

**Architecture:** Immutable raw runs form verified parent chains; builders merge the verified chain into complete processed snapshots. A lightweight daily decision report replaces daily full backtests, and a top-level cycle stages every account/output mutation before an atomic commit.

**Tech Stack:** Python 3.11+, standard library, existing AkShare adapters, CSV/JSONL artifacts, SHA-256 manifests, `unittest`/`pytest`.

## Global Constraints

- Live brokerage integration and real orders remain forbidden.
- The scored multi-factor baseline is the only paper stock-selection engine; DQN is diagnostic only.
- Incremental signal-price chains must use stable `hfq`; `qfq` chains fail closed.
- Preserve thresholds: buy score 70, confidence 0.8, max position 8%, reduce at 8%, liquidate at 9%, validate at 10%.
- Signal date D executes no earlier than D+1 open and marks NAV at D+1 close.
- Any constituent, freshness, coverage, variation, leakage, manifest, timeout, execution, or evidence failure leaves the canonical paper account byte-for-byte unchanged.
- Every behavior change follows RED → GREEN → full regression; no threshold tuning is permitted.

---

### Task 1: Verified raw-manifest parent chains

**Files:**
- Create: `src/fintech_quant/data/manifest_chain.py`
- Modify: `src/fintech_quant/data/__init__.py`
- Test: `tests/test_manifest_chain.py`

**Interfaces:**
- Produces: `load_verified_manifest_chain(path: Path, *, expected_layer: str) -> tuple[VerifiedManifest, ...]`, ordered oldest to newest.
- Produces: `VerifiedManifest(path: Path, payload: Mapping[str, object], artifacts: Mapping[str, Path])`.
- Guarantees: every manifest/artifact exists, artifact SHA matches, parent cycles fail, and parent paths resolve exactly as recorded.

- [ ] **Step 1: Write failing tests for order, hash verification and cycle rejection**

```python
def test_loads_verified_parent_chain_oldest_first(self):
    parent = write_run("parent", parent=None, rows=[{"value": 1}])
    child = write_run("child", parent=parent, rows=[{"value": 2}])
    chain = load_verified_manifest_chain(child, expected_layer="raw")
    self.assertEqual([item.payload["run_id"] for item in chain], ["parent", "child"])

def test_rejects_tampered_artifact(self):
    manifest = write_run("run", parent=None, rows=[{"value": 1}])
    (manifest.parent / "rows.jsonl").write_text("tampered\n")
    with self.assertRaisesRegex(ValueError, "artifact hash mismatch"):
        load_verified_manifest_chain(manifest, expected_layer="raw")

def test_rejects_parent_cycle(self):
    manifest = write_self_referencing_manifest()
    with self.assertRaisesRegex(ValueError, "manifest parent cycle"):
        load_verified_manifest_chain(manifest, expected_layer="raw")
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/test_manifest_chain.py -q`

Expected: import failure because `manifest_chain` does not exist.

- [ ] **Step 3: Implement the minimal verified-chain loader**

```python
@dataclass(frozen=True)
class VerifiedManifest:
    path: Path
    payload: Mapping[str, object]
    artifacts: Mapping[str, Path]

def load_verified_manifest_chain(path: Path, *, expected_layer: str):
    seen: set[Path] = set()
    result: list[VerifiedManifest] = []
    current: Path | None = path.resolve()
    while current is not None:
        if current in seen:
            raise ValueError("manifest parent cycle")
        seen.add(current)
        payload = _read_manifest(current, expected_layer)
        artifacts = _verify_artifacts(current, payload)
        result.append(VerifiedManifest(current, payload, artifacts))
        parent = payload.get("parent_manifest")
        current = Path(str(parent)).resolve() if parent else None
    return tuple(reversed(result))
```

- [ ] **Step 4: Run GREEN and the data-artifact regression tests**

Run: `.venv/bin/python -m pytest tests/test_manifest_chain.py tests/test_run_artifacts.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/fintech_quant/data/manifest_chain.py src/fintech_quant/data/__init__.py tests/test_manifest_chain.py
git commit -m "feat: verify immutable raw manifest chains"
```

### Task 2: Incremental collectors and chain-aware builders

**Files:**
- Modify: `scripts/collect_historical_prices.py`
- Modify: `scripts/collect_point_in_time_factors.py`
- Modify: `scripts/collect_corporate_actions.py`
- Modify: `scripts/build_historical_price_features.py`
- Modify: `scripts/build_point_in_time_factors.py`
- Modify: `scripts/build_corporate_actions.py`
- Modify: `tests/test_collect_historical_prices_script.py`
- Modify: `tests/test_collect_point_in_time_factors_script.py`
- Modify: `tests/test_corporate_action_scripts.py`
- Modify: `tests/test_build_historical_price_features_script.py`
- Modify: `tests/test_build_point_in_time_factors_script.py`

**Interfaces:**
- Collectors accept `--append-from <raw manifest>` and record it as `parent_manifest` while still fetching every requested scope for the new date range.
- Price builder merges by `(symbol, trade_date)`, child wins, then recomputes all technical features.
- Factor builder deduplicates `InformationRecord.record_id`, child wins, rematerializes full fundamentals and price-volume flow.
- Corporate-action builder loads the full verified chain, uses minimum chain start and maximum chain end, materializes each manifest independently, then lets child normalized events override parent events by `(symbol, ex_date, action_type)`.

- [ ] **Step 1: Add failing CLI tests for `--append-from` without scope reuse**

```python
completed = run_collector(
    "--start", "2026-01-03", "--end", "2026-01-03",
    "--append-from", str(parent_manifest),
)
self.assertEqual(completed.returncode, 0)
payload = json.loads(child_manifest.read_text())
self.assertEqual(Path(payload["parent_manifest"]), parent_manifest.resolve())
self.assertEqual(payload["scopes"][0]["status"], "success")
self.assertEqual(payload["request"]["start"], "2026-01-03")
```

- [ ] **Step 2: Run collector RED tests**

Run: `.venv/bin/python -m pytest tests/test_collect_historical_prices_script.py tests/test_collect_point_in_time_factors_script.py tests/test_corporate_action_scripts.py -q`

Expected: argparse rejects `--append-from`.

- [ ] **Step 3: Add `--append-from` to all three collectors**

```python
parser.add_argument("--append-from", default=None)
if args.append_from and args.resume_from:
    raise SystemExit("--append-from and --resume-from cannot be used together")
append_path = Path(args.append_from).resolve() if args.append_from else None
if append_path:
    load_verified_manifest_chain(append_path, expected_layer="raw")
store = RunArtifactStore(..., parent_manifest=str(append_path) if append_path else ...)
```

`--resume-from` keeps its existing same-request failed-scope recovery meaning. `--append-from` never copies a parent scope.

- [ ] **Step 4: Run collector GREEN tests**

Run the command from Step 2. Expected: all pass.

- [ ] **Step 5: Add failing builder tests for parent merge and child override**

```python
rows = build_price_chain(parent_date_close=10.0, child_same_date_close=11.0, child_new_close=12.0)
self.assertEqual([(r["trade_date"], r["close"]) for r in rows], [
    ("2026-01-02", "11.0"), ("2026-01-05", "12.0")
])

fundamentals = build_factor_chain(parent_records, child_records)
self.assertEqual(latest(fundamentals, "000001.SZ")["pe"], "9.0")
self.assertEqual(latest(fundamentals, "000001.SZ")["roe"], "0.12")

actions = build_action_chain(parent_future_action, child_request_end="2026-01-10")
self.assertEqual(actions[0]["ex_date"], "2026-01-10")
```

- [ ] **Step 6: Run builder RED tests**

Run: `.venv/bin/python -m pytest tests/test_build_historical_price_features_script.py tests/test_build_point_in_time_factors_script.py tests/test_corporate_action_scripts.py -q`

Expected: parent rows are missing.

- [ ] **Step 7: Implement verified chain merge in each builder**

Use `load_verified_manifest_chain`. For prices assign `rows[(symbol, trade_date)] = normalized_row` while iterating oldest to newest. For factor records assign `records_by_group[group][record.record_id] = record`. For actions concatenate verified raw rows oldest to newest and let `materialize_cninfo_corporate_actions` return the normalized unique ledger over the chain-wide date range. Record `raw_manifest_chain` as a list of `{path, sha256}` in the processed request.

- [ ] **Step 8: Run builder GREEN and collector/builder regression tests**

Run: `.venv/bin/python -m pytest tests/test_collect_historical_prices_script.py tests/test_build_historical_price_features_script.py tests/test_collect_point_in_time_factors_script.py tests/test_build_point_in_time_factors_script.py tests/test_corporate_action_scripts.py -q`

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add scripts/collect_historical_prices.py scripts/collect_point_in_time_factors.py scripts/collect_corporate_actions.py scripts/build_historical_price_features.py scripts/build_point_in_time_factors.py scripts/build_corporate_actions.py tests/test_collect_historical_prices_script.py tests/test_collect_point_in_time_factors_script.py tests/test_corporate_action_scripts.py tests/test_build_historical_price_features_script.py tests/test_build_point_in_time_factors_script.py
git commit -m "feat: build CSI300 snapshots from incremental raw chains"
```

### Task 3: Lightweight, fresh daily decision report

**Files:**
- Create: `src/fintech_quant/research/daily_decision.py`
- Create: `scripts/build_daily_decision_report.py`
- Create: `tests/test_daily_decision_report.py`
- Create: `tests/test_build_daily_decision_report_script.py`
- Modify: `src/fintech_quant/research/__init__.py`

**Interfaces:**
- Produces: `build_daily_decision_report(dataset, *, as_of, data_health, input_refs, limits) -> dict[str, object]`.
- Output contains only the requested date's `scores` and `risk_warnings`, plus `data_health_passed`, input hashes, limits and Git SHA.
- Rejects when latest feature/market date differs from `as_of`, active member count differs from 300, or health did not pass.

- [ ] **Step 1: Write failing unit tests for one-day output and stale-date rejection**

```python
report = build_daily_decision_report(dataset, as_of=date(2026, 1, 5), data_health=passing_health)
self.assertEqual({row["trade_date"] for row in report["scores"]}, {"2026-01-05"})
self.assertEqual(len(report["scores"]), 300)

with self.assertRaisesRegex(ValueError, "latest feature date"):
    build_daily_decision_report(dataset, as_of=date(2026, 1, 6), data_health=passing_health)
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/test_daily_decision_report.py -q`

Expected: import failure.

- [ ] **Step 3: Implement daily scoring and static risk evaluation**

Build all scores using the existing point-in-time scorer, retain only `as_of`, build neutral-position risk inputs for `as_of`, evaluate with the unchanged `RiskLimits`, and serialize warnings with existing rule/action names. Do not run a backtest or create an RL dataset.

- [ ] **Step 4: Run GREEN**

Run: `.venv/bin/python -m pytest tests/test_daily_decision_report.py -q`

Expected: all pass.

- [ ] **Step 5: Write CLI RED test requiring verified manifests and health**

The fixture command passes processed factor, price, execution-price and corporate-action manifests plus benchmark/membership. Assert the report has the exact input SHA values and that a stale benchmark returns non-zero without an output report.

- [ ] **Step 6: Implement CLI and run GREEN**

Run: `.venv/bin/python -m pytest tests/test_build_daily_decision_report_script.py tests/test_daily_decision_report.py -q`

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/fintech_quant/research/daily_decision.py src/fintech_quant/research/__init__.py scripts/build_daily_decision_report.py tests/test_daily_decision_report.py tests/test_build_daily_decision_report_script.py
git commit -m "feat: emit fresh CSI300 daily decision reports"
```

### Task 4: Execute-then-score paper sequencing and atomic account commit

**Files:**
- Modify: `scripts/run_daily_paper_trading.py`
- Modify: `scripts/run_post_close_daily_cycle.py`
- Modify: `tests/test_daily_paper_trading_script.py`
- Modify: `tests/test_run_post_close_daily_cycle_script.py`

**Interfaces:**
- `run_daily_paper_trading.py` executes `account.pending_targets` first, then derives actual-position risk at the close and queues the new raw targets.
- `run_post_close_daily_cycle.py` stages account, targets, report and dashboard in the destination filesystem and replaces canonical files only after every child command and hash check succeeds.
- Repeated `as_of` with a matching cycle manifest returns `already_completed`; inconsistent duplicate dates fail.

- [ ] **Step 1: Add RED test proving current-close position drawdown blocks a newly selected held stock**

```python
account = held_position(cost_basis=10.0, pending_targets={})
bars = one_day_bar(open=9.5, close=9.0)
run_daily_paper(...)
self.assertEqual(load_account().pending_targets, {})
self.assertIn("single_position_drawdown", load_report()["target_risk_warnings"][0]["rule"])
```

- [ ] **Step 2: Run RED and implement execute-then-score ordering**

Run: `.venv/bin/python -m pytest tests/test_daily_paper_trading_script.py -q`

Expected before implementation: the held stock remains queued. After implementation: pass.

- [ ] **Step 3: Add RED tests for account rollback and idempotence**

```python
before = account.read_bytes()
completed = run_cycle(fail_dashboard=True)
self.assertNotEqual(completed.returncode, 0)
self.assertEqual(account.read_bytes(), before)

first = run_cycle()
after = account.read_bytes()
second = run_cycle()
self.assertEqual(second.returncode, 0)
self.assertIn("already_completed=true", second.stdout)
self.assertEqual(account.read_bytes(), after)
```

- [ ] **Step 4: Implement staging, cycle manifest and atomic replacement**

Use `tempfile.TemporaryDirectory(dir=account.parent)`; copy the account into staging, run child commands only against staged paths, write hashes, `fsync` files, and call `os.replace` only after all validations pass. Acquire an exclusive `fcntl.flock` on `<account>.lock` for the complete operation.

- [ ] **Step 5: Run GREEN and paper regressions**

Run: `.venv/bin/python -m pytest tests/test_daily_paper_trading_script.py tests/test_paper_trading_loop.py tests/test_run_post_close_daily_cycle_script.py -q`

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/run_daily_paper_trading.py scripts/run_post_close_daily_cycle.py tests/test_daily_paper_trading_script.py tests/test_run_post_close_daily_cycle_script.py
git commit -m "fix: commit post-close paper cycles atomically"
```

### Task 5: Deterministic CSI 300 top-level post-close CLI

**Files:**
- Create: `scripts/run_csi300_post_close.py`
- Create: `tests/test_run_csi300_post_close_script.py`
- Modify: `README.md`

**Interfaces:**
- CLI requires `--as-of`, `--state`, `--account`, `--membership` and runtime roots.
- Pipeline state stores last successful date and the latest raw/processed manifest for signal prices, execution prices, factors and corporate actions.
- Every subprocess has a hard timeout and receives explicit paths; no globbing for “latest”.
- Current constituents are fetched to the cycle staging directory, must total 300, and must equal `active_symbols(membership, as_of)`.

- [ ] **Step 1: Write orchestration RED tests with a recording fake runner**

Assert exact order: constituent verification → signal-price delta/build → execution-price delta/build → factor delta/build → action delta/build → benchmark → daily decision → atomic paper cycle. Assert `start == previous_as_of + 1 day`, no DQN argument occurs, and a timeout stops before account execution.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/test_run_csi300_post_close_script.py -q`

Expected: script/module missing.

- [ ] **Step 3: Implement state parsing, command construction and timeout runner**

```python
def _run(command: Sequence[str], *, timeout: int) -> None:
    subprocess.run([sys.executable, *command], cwd=ROOT, check=True, timeout=timeout)

def _next_start(last_as_of: date) -> date:
    return last_as_of + timedelta(days=1)
```

Resolve every produced manifest from the exact deterministic run directory and verify it before updating staged pipeline state.

- [ ] **Step 4: Implement constituent equality and state atomic update**

Read exactly 300 unique normalized symbols from the fetched CSV and compare to `active_symbols(load_membership_intervals(...), as_of)`. Pass the staged state to `os.replace` only after the atomic paper cycle succeeds.

- [ ] **Step 5: Run GREEN, CLI help and focused integration tests**

Run: `.venv/bin/python -m pytest tests/test_run_csi300_post_close_script.py tests/test_run_post_close_daily_cycle_script.py -q && .venv/bin/python scripts/run_csi300_post_close.py --help >/dev/null`

Expected: all pass, help exits zero.

- [ ] **Step 6: Document bootstrap state and operations**

README must show one command, fail-closed semantics, evidence directory, how to inspect a failed run, and explicitly state that it never places real orders.

- [ ] **Step 7: Commit**

```bash
git add scripts/run_csi300_post_close.py tests/test_run_csi300_post_close_script.py README.md
git commit -m "feat: add deterministic CSI300 post-close entrypoint"
```

### Task 6: Full review, real-data handoff and automation switch

**Files:**
- Modify only if review finds an in-scope defect.
- Runtime only: `data/paper/csi300_baseline/pipeline_state.json`
- Runtime only: `outputs/paper_trading/csi300_baseline/cycles/<as_of>/`

- [ ] **Step 1: Run complete verification**

Run:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src scripts tests
.venv/bin/python scripts/run_csi300_post_close.py --help >/dev/null
git diff --check
git status --short
```

Expected: full suite passes, compile/help/diff checks exit zero, only intended tracked changes remain.

- [ ] **Step 2: Run the fixed fixture end-to-end twice**

First run must queue D targets, second run must execute them at D+1 open and queue D+1 targets. Re-running D+1 must print `already_completed=true`, leave account hash unchanged and record no duplicate trade.

- [ ] **Step 3: Review the current real-data automation result before seeding state**

Verify exactly 300 current members, all price/factor/action scopes, latest feature/execution/benchmark dates, data health, company-action types, account date and report hashes. Do not seed from a failed or partial artifact.

- [ ] **Step 4: Seed pipeline state from the latest complete real run and run a dry preflight**

The preflight may write diagnostic cycle artifacts but must not mutate the canonical account. If the latest real run is incomplete, preserve its evidence and leave the eight-week clock unstarted.

- [ ] **Step 5: Request code review and fix only verified findings**

Use `superpowers:requesting-code-review`, then re-run Step 1 after any change.

- [ ] **Step 6: Commit, push, merge to main and reverify main**

```bash
git push origin codex/csi300-post-close-cycle
```

After merge, run the Step 1 verification from `main` and confirm `main == origin/main`.

- [ ] **Step 7: Update the existing Codex automation**

Replace free-form command selection with one explicit `run_csi300_post_close.py` command. Keep weekday 17:30 scheduling, baseline-only exposure, fail-closed reporting and the live-broker prohibition.

- [ ] **Step 8: Start evidence clock only on a proven successful fresh cycle**

The first counted date requires a current-date cycle manifest, passing data health, atomic account commit and reproducible hashes. Historical bootstrap dates do not count.
