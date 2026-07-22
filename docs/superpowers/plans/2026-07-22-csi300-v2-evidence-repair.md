# CSI 300 V2 Evidence Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair processed-factor reuse, validation-epoch recovery, pre-commit session continuity, and latest-audit publication without modifying preserved V2 evidence.

**Architecture:** Keep the current daily entrypoint and immutable directory layout. Extend processed-stage reuse with explicit material hashes, add a hash-linked superseding anchor plus active `evidence_parent`, reject skipped benchmark sessions before paper execution, and publish one byte-identical audit through cycle-local, root, state, and command-result surfaces.

**Tech Stack:** Python 3.14, standard library, pytest/unittest, existing SHA-256 manifest and atomic-file helpers.

## Global Constraints

- Never edit or delete the original anchor, the 2026-07-14 partial directory, or the failed 2026-07-15 cycle.
- Keep the scored baseline policy, thresholds, costs, drawdown controls, DQN-off flag, and live-off flag unchanged.
- Keep strict anchor-to-latest CSI 300 session continuity; do not reinterpret it as first-cycle-to-latest continuity.
- Write every regression test first and observe the expected failure before production edits.
- Use only local fixtures during implementation; do not run a provider-backed post-close cycle.

---

## File Structure

- `scripts/run_csi300_post_close.py`: processed-stage reuse, active evidence-parent selection,
  pre-commit session check, audit mirroring, and pipeline-state audit reference.
- `src/fintech_quant/execution/paper_evidence.py`: superseding-anchor schema, verified historical
  references, and collision-free immutable anchor directories.
- `scripts/initialize_csi300_paper_validation.py`: explicit supersession CLI and atomic active-epoch
  state transition.
- `src/fintech_quant/reports/paper_validation.py`: active-epoch filtering of preserved older cycles.
- `tests/test_run_csi300_post_close_script.py`: same-date factor retry, session precheck, and canonical
  audit publication regressions.
- `tests/test_paper_evidence.py`: superseding-anchor unit validation.
- `tests/test_initialize_csi300_paper_validation_script.py`: supersession CLI/state integration.
- `tests/test_paper_validation.py`: new-epoch audit scope regression.
- `README.md`, `handoff.md`, and `AGENTS.md`: operator command and repaired-status documentation.

### Task 1: Bind Processed-Factor Reuse to Material Dependencies

**Files:**
- Modify: `tests/test_run_csi300_post_close_script.py`
- Modify: `scripts/run_csi300_post_close.py`

**Interfaces:**
- Consumes: existing processed-manifest `request` fields written by
  `scripts/build_point_in_time_factors.py`.
- Produces: `_processed_stage_attempt(root: Path, *, base_run_id: str, raw_manifest: Path,
  material_sha256: Mapping[str, str] | None = None) -> ProcessedStageAttempt`.

- [ ] **Step 1: Write failing reuse tests**

Add focused tests that create a completed processed factor manifest with the correct raw-parent
reference and stale material hashes, then invoke `_processed_stage_attempt()` directly:

```python
def test_processed_factor_retry_rejects_stale_material_dependencies(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        raw = root / "raw/manifest.json"
        _write_manifest(raw, layer="raw")
        completed = root / "processed/csi300-factor-20260714/manifest.json"
        _write_manifest(
            completed,
            layer="processed",
            parent=str(raw.resolve()),
            request={
                "parent_manifest_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
                "trading_calendar_sha256": "old-calendar",
                "price_features_sha256": "old-features",
            },
        )

        attempt = _processed_stage_attempt(
            root / "processed",
            base_run_id="csi300-factor-20260714",
            raw_manifest=raw,
            material_sha256={
                "trading_calendar_sha256": "new-calendar",
                "price_features_sha256": "new-features",
            },
        )

        self.assertTrue(attempt.needs_run)
        self.assertEqual(attempt.run_id, "csi300-factor-20260714-retry-1")
```

Add the matching reuse test with equal hashes and assert `needs_run is False` and the original run
ID is returned. Import `_processed_stage_attempt` beside `_raw_stage_attempt`.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
pytest -q tests/test_run_csi300_post_close_script.py -k 'processed_factor_retry'
```

Expected: failure because `_processed_stage_attempt()` does not accept `material_sha256` and would
otherwise reuse the stale output.

- [ ] **Step 3: Implement the minimum dependency check**

Change the function to normalize the optional mapping and require every supplied key to match:

```python
def _processed_stage_attempt(
    root: Path,
    *,
    base_run_id: str,
    raw_manifest: Path,
    material_sha256: Mapping[str, str] | None = None,
) -> ProcessedStageAttempt:
    attempt = 0
    raw_sha256 = sha256_file(raw_manifest)
    required = dict(material_sha256 or {})
    while True:
        run_id = base_run_id if attempt == 0 else f"{base_run_id}-retry-{attempt}"
        run_dir = root / run_id
        manifest = run_dir / "manifest.json"
        if not run_dir.exists():
            return ProcessedStageAttempt(run_id, manifest, True)
        if manifest.is_file():
            verified = load_verified_manifest(manifest, expected_layer="processed")
            request = verified.payload.get("request")
            parent = Path(str(verified.payload.get("parent_manifest", ""))).resolve()
            material_matches = isinstance(request, Mapping) and all(
                request.get(name) == value for name, value in required.items()
            )
            if (
                isinstance(request, Mapping)
                and request.get("parent_manifest_sha256") == raw_sha256
                and parent == raw_manifest.resolve()
                and material_matches
            ):
                return ProcessedStageAttempt(run_id, manifest.resolve(), False)
        attempt += 1
```

In `_factor_stage()`, pass the hashes of the exact paths already supplied to the builder:

```python
processed_attempt = _processed_stage_attempt(
    config.processed_factor_root,
    base_run_id=f"csi300-factor-{date_token}",
    raw_manifest=raw_manifest,
    material_sha256={
        "trading_calendar_sha256": sha256_file(benchmark),
        "price_features_sha256": sha256_file(signal_features),
    },
)
```

Update `RecordingRunner` so processed factor fixtures record these two hashes from the build
command; keep non-factor processed fixtures unchanged.

- [ ] **Step 4: Run focused and existing post-close tests**

Run:

```bash
pytest -q tests/test_run_csi300_post_close_script.py
```

Expected: all tests pass, including stale-hash retry and equal-hash reuse.

- [ ] **Step 5: Commit the factor fix**

```bash
git add scripts/run_csi300_post_close.py tests/test_run_csi300_post_close_script.py
git commit -m "fix: bind factor reuse to material inputs"
```

### Task 2: Add Explicit Validation-Epoch Supersession

**Files:**
- Modify: `tests/test_paper_evidence.py`
- Modify: `src/fintech_quant/execution/paper_evidence.py`
- Modify: `tests/test_initialize_csi300_paper_validation_script.py`
- Modify: `scripts/initialize_csi300_paper_validation.py`

**Interfaces:**
- Consumes: verified `validation_anchor`, optional `cycle_manifest`, and optional
  `validation_report` references from pipeline state.
- Produces: `create_validation_anchor(..., supersedes: Mapping[str, Mapping[str, object]] | None =
  None) -> Path` and CLI flag `--supersede-current-epoch`.

- [ ] **Step 1: Write a failing anchor-unit test**

Extend the existing anchor fixture to create a first anchor, attach verified references for it and
a preserved cycle, then create a superseding anchor:

```python
superseding = create_validation_anchor(
    account=paths["account"],
    pipeline_state=paths["state"],
    formal_run_manifest=paths["formal_manifest"],
    comparison=paths["comparison"],
    benchmark=paths["benchmark"],
    output_root=paths["validation"],
    created_at="2026-07-16T09:00:00+00:00",
    git_sha="def456",
    supersedes={
        "validation_anchor": file_reference(first),
        "cycle_manifest": file_reference(cycle),
    },
)
payload = load_verified_anchor(superseding)
assert payload["schema_version"] == 2
assert verify_file_reference(payload["supersedes"]["validation_anchor"]) == first.resolve()
assert verify_file_reference(payload["supersedes"]["cycle_manifest"]) == cycle.resolve()
assert first.read_bytes() == first_before
```

- [ ] **Step 2: Run the unit test and verify RED**

Run:

```bash
pytest -q tests/test_paper_evidence.py -k superseding
```

Expected: failure because `create_validation_anchor()` has no `supersedes` parameter.

- [ ] **Step 3: Implement schema-2 superseding anchors**

Add `supersedes` to the function signature. Verify every supplied reference with
`verify_file_reference()`, choose `anchor-YYYYMMDD-epoch-N` for superseding anchors using the first
unused integer starting at 2, and write:

```python
payload = {
    "schema_version": 2 if supersedes else 1,
    "kind": "paper_validation_anchor",
    "as_of": account_date,
    "created_at": created_at,
    "git_sha": git_sha,
    "counts_toward_evidence": False,
    "anchor_equity": _anchor_equity(account_payload, account_date),
    "drawdown_regime": _drawdown_regime(account_payload),
    "policy": approved_paper_policy(),
    "artifacts": {
        name: file_reference(path) for name, path in snapshots.items()
    },
    "data_manifests": state_payload.get("manifests"),
}
if supersedes:
    payload["supersedes"] = {
        name: dict(reference) for name, reference in sorted(supersedes.items())
    }
```

Update `load_verified_anchor()` to accept schema 1 or 2. Require schema 2 to contain a non-empty
`supersedes` mapping and verify every reference; reject `supersedes` on schema 1.

- [ ] **Step 4: Write failing CLI supersession tests**

Add a helper option to `_run()` and a test that initializes once, attaches a cycle and validation
report to state, then reruns with `--supersede-current-epoch`. Assert:

```python
state_after = _load_json(paths["state"])
new_anchor = Path(state_after["validation_anchor"]["path"])
assert new_anchor != old_anchor
assert state_after["evidence_parent"] == state_after["validation_anchor"]
payload = load_verified_anchor(new_anchor)
assert verify_file_reference(payload["supersedes"]["validation_anchor"]) == old_anchor
assert verify_file_reference(payload["supersedes"]["cycle_manifest"]) == cycle.resolve()
assert old_anchor.read_bytes() == old_anchor_before
assert cycle.read_bytes() == cycle_before
```

Also assert that invoking normal initialization a second time still fails without changing state.

- [ ] **Step 5: Run the CLI test and verify RED**

Run:

```bash
pytest -q tests/test_initialize_csi300_paper_validation_script.py -k supersede
```

Expected: argparse rejects `--supersede-current-epoch`.

- [ ] **Step 6: Implement the explicit CLI transition**

Add the flag and construct verified historical references:

```python
parser.add_argument("--supersede-current-epoch", action="store_true")

existing_anchor = state.get("validation_anchor")
if existing_anchor is not None and not args.supersede_current_epoch:
    raise ValueError("pipeline state already contains a validation anchor")
if existing_anchor is None and args.supersede_current_epoch:
    raise ValueError("validation epoch supersession requires an existing anchor")

supersedes = None
if args.supersede_current_epoch:
    supersedes = {"validation_anchor": _verified_state_reference(state, "validation_anchor")}
    for name in ("cycle_manifest", "validation_report"):
        if isinstance(state.get(name), Mapping):
            supersedes[name] = _verified_state_reference(state, name)
```

Pass `supersedes` into `create_validation_anchor()`. After verification, atomically write:

```python
anchor_reference = file_reference(manifest)
next_state = {
    **state,
    "validation_anchor": anchor_reference,
    "evidence_parent": anchor_reference,
}
```

The helper `_verified_state_reference()` must call `verify_file_reference()` and return a copied
mapping so no unverified path enters the new anchor.

- [ ] **Step 7: Run all anchor tests**

Run:

```bash
pytest -q tests/test_paper_evidence.py tests/test_initialize_csi300_paper_validation_script.py
```

Expected: all tests pass and normal second initialization still fails closed.

- [ ] **Step 8: Commit the epoch support**

```bash
git add src/fintech_quant/execution/paper_evidence.py \
  scripts/initialize_csi300_paper_validation.py \
  tests/test_paper_evidence.py \
  tests/test_initialize_csi300_paper_validation_script.py
git commit -m "feat: add auditable validation epoch supersession"
```

### Task 3: Enforce Active-Epoch Session Continuity Before Paper Execution

**Files:**
- Modify: `tests/test_paper_validation.py`
- Modify: `src/fintech_quant/reports/paper_validation.py`
- Modify: `tests/test_run_csi300_post_close_script.py`
- Modify: `scripts/run_csi300_post_close.py`

**Interfaces:**
- Consumes: active anchor/cycle `as_of` and the refreshed benchmark `trade_date` column.
- Produces: `_require_next_validation_session(evidence_parent: Path, benchmark: Path,
  as_of: date) -> None`.

- [ ] **Step 1: Write a failing auditor epoch-scope test**

Use the existing paper-validation fixture to place a preserved V2 cycle on the new anchor date and
a valid later cycle chained to the new anchor. Audit with the new anchor and both paths:

```python
report = audit_paper_validation(new_anchor, [preserved_cycle, active_cycle])
assert report["metrics"]["valid_sessions"] == 1
assert report["latest_cycle"]["path"] == str(active_cycle.resolve())
```

- [ ] **Step 2: Run the auditor test and verify RED**

Run:

```bash
pytest -q tests/test_paper_validation.py -k new_epoch
```

Expected: `ValueError: paper cycle date must be after validation anchor` for the preserved cycle.

- [ ] **Step 3: Scope cycles to the active epoch**

In `_load_v2_cycles()`, keep validating the manifest schema but skip historical cycles instead of
raising:

```python
cycle_date = date.fromisoformat(str(payload.get("as_of", "")))
if cycle_date <= anchor_date:
    continue
result.append((path, payload, cycle_date))
```

The existing evidence-parent loop continues to reject every later unrelated or broken chain.

- [ ] **Step 4: Write failing pre-commit continuity tests**

Add one pipeline test whose benchmark runner writes both `2026-01-05` and `2026-01-06` while the
requested date is `2026-01-06` and active parent remains `2026-01-02`. Assert the pipeline raises
`validation session continuity` before `run_post_close_daily_cycle.py`, and account/state bytes are
unchanged. Add a passing test with parent date Friday and requested date Monday where the benchmark
contains only Monday after the parent.

- [ ] **Step 5: Run continuity tests and verify RED**

Run:

```bash
pytest -q tests/test_run_csi300_post_close_script.py -k 'session_continuity or weekend'
```

Expected: the missing-session case currently reaches paper execution instead of failing early.

- [ ] **Step 6: Select and advance an explicit active parent**

At pipeline start, use `evidence_parent` when present and verified; otherwise retain backward
compatibility:

```python
evidence_parent = (
    _verified_reference(state, "evidence_parent")
    if isinstance(state.get("evidence_parent"), Mapping)
    else _verified_reference(state, "cycle_manifest")
    if isinstance(state.get("cycle_manifest"), Mapping)
    else validation_anchor
)
```

After a successful cycle, set both:

```python
cycle_reference = _reference(cycle_manifest)
new_state["cycle_manifest"] = cycle_reference
new_state["evidence_parent"] = cycle_reference
```

- [ ] **Step 7: Implement the benchmark-session precheck**

Immediately after the benchmark file is produced, call:

```python
_require_next_validation_session(evidence_parent, benchmark, config.as_of)
```

Implement it with `csv.DictReader`, strict sorted/unique dates, and exact next-session semantics:

```python
def _require_next_validation_session(
    evidence_parent: Path, benchmark: Path, as_of: date
) -> None:
    parent_payload = _load_json(evidence_parent)
    parent_date = date.fromisoformat(str(parent_payload.get("as_of", "")))
    with benchmark.open(encoding="utf-8", newline="") as handle:
        raw_dates = [date.fromisoformat(str(row["trade_date"])) for row in csv.DictReader(handle)]
    if raw_dates != sorted(set(raw_dates)):
        raise ValueError("benchmark trading sessions must be unique and increasing")
    pending = [value for value in raw_dates if parent_date < value <= as_of]
    if pending != [as_of]:
        raise ValueError(
            "validation session continuity failed before paper execution: "
            f"parent={parent_date.isoformat()} as_of={as_of.isoformat()} "
            f"sessions={[value.isoformat() for value in pending]}"
        )
```

- [ ] **Step 8: Run auditor and pipeline tests**

Run:

```bash
pytest -q tests/test_paper_validation.py tests/test_run_csi300_post_close_script.py
```

Expected: all active-epoch and pre-commit continuity tests pass.

- [ ] **Step 9: Commit the continuity repair**

```bash
git add src/fintech_quant/reports/paper_validation.py \
  scripts/run_csi300_post_close.py \
  tests/test_paper_validation.py \
  tests/test_run_csi300_post_close_script.py
git commit -m "fix: reject V2 session gaps before paper commit"
```

### Task 4: Publish One Canonical Latest Audit

**Files:**
- Modify: `tests/test_run_csi300_post_close_script.py`
- Modify: `scripts/run_csi300_post_close.py`

**Interfaces:**
- Consumes: validated cycle-local audit report.
- Produces: byte-identical root `validation_report.json`, pipeline-state `validation_report`
  reference to the immutable cycle-local report, and command result derived from that report.

- [ ] **Step 1: Write failing publication and replay tests**

Extend the successful pipeline test and same-date replay test:

```python
cycle_report = config.cycle_root / config.as_of.isoformat() / "validation_report.json"
root_report = config.cycle_root.parent / "validation_report.json"
state_after = json.loads(config.state.read_text(encoding="utf-8"))
assert root_report.read_bytes() == cycle_report.read_bytes()
assert state_after["validation_report"] == {
    "path": str(cycle_report.resolve()),
    "bytes": cycle_report.stat().st_size,
    "sha256": hashlib.sha256(cycle_report.read_bytes()).hexdigest(),
}
assert result["validation_report"] == str(cycle_report)
assert result["validation_status"] == json.loads(cycle_report.read_text())["status"]
```

For same-date replay, first overwrite the root report with stale bytes, run again, and assert it is
restored from the new cycle-local audit while the account bytes remain unchanged.

- [ ] **Step 2: Run publication tests and verify RED**

Run:

```bash
pytest -q tests/test_run_csi300_post_close_script.py -k 'runs_explicit or same_date_replay'
```

Expected: the root report and pipeline-state `validation_report` reference are missing.

- [ ] **Step 3: Add atomic root publication**

After validating the cycle-local report in `_run_validation_audit()`, atomically copy its exact
bytes to `config.cycle_root.parent / "validation_report.json"`:

```python
root_output = config.cycle_root.parent / "validation_report.json"
_copy_file_atomic(output, root_output)
if sha256_file(root_output) != sha256_file(output):
    raise ValueError("root validation report differs from cycle-local report")
```

Implement `_copy_file_atomic()` with a UUID-named sibling, `shutil.copyfile()`, `_fsync_file()`,
`os.replace()`, `_fsync_directory()`, and cleanup in `finally`. Add the standard-library `shutil`
import.

- [ ] **Step 4: Store the immutable report reference after successful audit**

For a new cycle, write the initial committed state as today, run the audit, then add the immutable
cycle-local reference and write state atomically again:

```python
validation_status, validation_report = _run_validation_audit(...)
new_state["validation_report"] = _reference(validation_report)
_write_state_atomic(config.state, new_state)
```

For same-date replay, copy the loaded state, replace only `validation_report`, and write it after a
successful audit. Do not change `last_successful_as_of`, account, manifests, or evidence parent.

- [ ] **Step 5: Run post-close tests**

Run:

```bash
pytest -q tests/test_run_csi300_post_close_script.py
```

Expected: all tests pass; audit subprocess failure still leaves the committed account/state behavior
covered by the existing test.

- [ ] **Step 6: Commit canonical audit publication**

```bash
git add scripts/run_csi300_post_close.py tests/test_run_csi300_post_close_script.py
git commit -m "fix: publish canonical V2 validation status"
```

### Task 5: Update Operations Documentation and Verify the Repair

**Files:**
- Modify: `README.md`
- Modify: `handoff.md`
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: completed implementation and verification output.
- Produces: exact supersession command semantics and current repaired-code status without claiming
  a counted V2 session.

- [ ] **Step 1: Update operator documentation**

Document `--supersede-current-epoch`, explain that it preserves and hash-links the old anchor/cycle,
and identify the cycle-local report as the immutable state reference with a byte-identical root
mirror. In `handoff.md` and `AGENTS.md`, mark the four code defects repaired but keep the accepted
session count at zero until a fresh provider-backed cycle passes `COLLECTING`.

- [ ] **Step 2: Run focused regression suites**

Run:

```bash
pytest -q \
  tests/test_run_csi300_post_close_script.py \
  tests/test_initialize_csi300_paper_validation_script.py \
  tests/test_paper_evidence.py \
  tests/test_paper_validation.py \
  tests/test_audit_csi300_paper_validation_script.py \
  tests/test_build_daily_decision_report_script.py
```

Expected: all focused tests pass.

- [ ] **Step 3: Run the full suite and static checks**

Run:

```bash
pytest -q
python -m compileall -q src scripts tests
python scripts/initialize_csi300_paper_validation.py --help >/dev/null
python scripts/run_csi300_post_close.py --help >/dev/null
python scripts/audit_csi300_paper_validation.py --help >/dev/null
python scripts/run_post_close_daily_cycle.py --help >/dev/null
if command -v ruff >/dev/null 2>&1; then ruff check src scripts tests; fi
git diff --check
```

Expected: pytest and compile/help checks exit zero; Ruff runs only when installed; diff check is
clean.

- [ ] **Step 4: Inspect the final diff for scope and immutable evidence**

Run:

```bash
git status --short
git diff --stat HEAD~4
git diff -- data/paper outputs/paper_trading
```

Expected: only source, tests, and documentation are changed; the final command shows no changes to
canonical account, old anchors, old cycles, dashboards, or reports.

- [ ] **Step 5: Commit documentation and verification record**

```bash
git add README.md handoff.md AGENTS.md
git commit -m "docs: record V2 evidence repair workflow"
```
