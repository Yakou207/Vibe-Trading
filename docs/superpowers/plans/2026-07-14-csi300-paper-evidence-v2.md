# CSI 300 Paper Evidence V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Build a hash-chained CSI 300 paper-validation record and deterministic eight-week readiness auditor before the first counted paper cycle.

**Architecture:** A non-counted immutable anchor snapshots the canonical bootstrap state. Each atomic paper cycle writes a V2 manifest that binds its parent, inputs, policy, account transition, and outputs; a separate deterministic auditor verifies the chain and calculates readiness gates without ever enabling live trading.

**Tech Stack:** Python 3.11+, standard library, JSON/CSV artifacts, SHA-256, existing paper account and immutable manifest modules, pytest/unittest.

## Global Constraints

- The scored 35/25/25/15 baseline is the only paper stock-selection engine.
- DQN exposure and live brokerage remain disabled.
- Entry score is 70, confidence is 0.8, and maximum stock weight is 0.08.
- Portfolio drawdown actions remain 8% reduce, 9% liquidate, and 10% validate.
- Signal prices require hfq; execution and mark-to-market prices require adjust=none.
- Paper costs are 0.0003 commission, CNY 5 minimum commission, date-specific stamp duty, individual dividend tax, and 0.0005 slippage.
- Rights issues use do_not_subscribe.
- V1 manifests and the 2026-07-13 bootstrap never count as validation evidence.
- The strongest possible result is ELIGIBLE_FOR_REVIEW, never live-trading authorization.
- Every behavior change follows RED → GREEN; commits remain surgical and independently verifiable.

---

### Task 1: Evidence primitives and immutable bootstrap anchor

**Files:**
- Create: src/fintech_quant/execution/paper_evidence.py
- Modify: src/fintech_quant/execution/__init__.py
- Create: scripts/initialize_csi300_paper_validation.py
- Create: tests/test_paper_evidence.py
- Create: tests/test_initialize_csi300_paper_validation_script.py

**Interfaces:**
- Produces approved_paper_policy() -> dict[str, object] with fixed baseline, drawdown, cost, adjustment, DQN, and live flags.
- Produces file_reference(path: Path) -> dict[str, object] and verify_file_reference(reference: Mapping[str, object]) -> Path.
- Produces canonical_json_sha256(payload: Mapping[str, object]) -> str using sorted indented JSON plus a trailing newline.
- Produces create_validation_anchor(...) -> Path and load_verified_anchor(path: Path) -> dict[str, object].

- [ ] **Step 1: Write failing tests for fixed policy, immutable snapshots, and date rejection**

    def test_approved_policy_records_cost_and_exposure_boundaries() -> None:
        policy = approved_paper_policy()
        assert policy["buy_threshold"] == 70.0
        assert policy["minimum_score_confidence"] == 0.8
        assert policy["maximum_position_weight"] == 0.08
        assert policy["slippage_rate"] == 0.0005
        assert policy["signal_adjust"] == "hfq"
        assert policy["execution_adjust"] == "none"
        assert policy["dqn_exposure_enabled"] is False
        assert policy["live_trading_enabled"] is False

    def test_create_anchor_copies_mutable_state_and_does_not_count(tmp_path: Path) -> None:
        paths = write_valid_bootstrap_fixture(tmp_path, as_of="2026-07-13")
        manifest = create_anchor_from_fixture(paths)
        payload = load_verified_anchor(manifest)
        assert payload["counts_toward_evidence"] is False
        assert Path(payload["artifacts"]["account"]["path"]) != paths.account
        paths.account.write_text("tampered\n", encoding="utf-8")
        assert load_verified_anchor(manifest)["as_of"] == "2026-07-13"

    def test_create_anchor_rejects_mismatched_account_and_state_dates(tmp_path: Path) -> None:
        paths = write_valid_bootstrap_fixture(tmp_path, as_of="2026-07-13")
        rewrite_account_date(paths.account, "2026-07-12")
        with pytest.raises(ValueError, match="account and pipeline state dates differ"):
            create_anchor_from_fixture(paths)

- [ ] **Step 2: Run RED**

Run: .venv/bin/python -m pytest tests/test_paper_evidence.py -q

Expected: collection fails because fintech_quant.execution.paper_evidence does not exist.

- [ ] **Step 3: Implement the minimal policy and reference helpers**

    def approved_paper_policy() -> dict[str, object]:
        return {
            "strategy": "scored_multi_factor_baseline",
            "buy_threshold": 70.0,
            "minimum_score_confidence": 0.8,
            "maximum_position_weight": 0.08,
            "drawdown_reduce": 0.08,
            "drawdown_liquidate": 0.09,
            "drawdown_validation_limit": 0.10,
            "commission_rate": 0.0003,
            "minimum_commission": 5.0,
            "slippage_rate": 0.0005,
            "stamp_duty": "date_specific_a_share_sell",
            "dividend_tax": "individual_fifo_20_10_0",
            "rights_issue_policy": "do_not_subscribe",
            "signal_adjust": "hfq",
            "execution_adjust": "none",
            "dqn_exposure_enabled": False,
            "live_trading_enabled": False,
        }

    def canonical_json_sha256(payload: Mapping[str, object]) -> str:
        data = (
            json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode()
        return hashlib.sha256(data).hexdigest()

    def file_reference(path: Path) -> dict[str, object]:
        resolved = path.resolve()
        return {
            "path": str(resolved),
            "bytes": resolved.stat().st_size,
            "sha256": sha256_file(resolved),
        }

Create anchor-<as_of> exclusively, copy account/state/formal manifest/comparison/benchmark, verify four state manifest groups, formal health, signal hfq, execution none, and date equality, then write anchor_manifest.json. Remove an incomplete newly-created directory on failure.

- [ ] **Step 4: Run unit GREEN**

Run: .venv/bin/python -m pytest tests/test_paper_evidence.py -q

Expected: all pass.

- [ ] **Step 5: Write the CLI RED test**

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/initialize_csi300_paper_validation.py",
            "--account", str(paths.account),
            "--state", str(paths.state),
            "--formal-run-manifest", str(paths.formal_manifest),
            "--comparison", str(paths.comparison),
            "--benchmark", str(paths.benchmark),
            "--output-root", str(tmp_path / "validation"),
            "--created-at", "2026-07-14T05:00:00+00:00",
        ],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    state = json.loads(paths.state.read_text())
    assert state["last_successful_as_of"] == "2026-07-13"
    assert state["validation_anchor"]["sha256"] == sha256_file(
        Path(state["validation_anchor"]["path"])
    )

- [ ] **Step 6: Run CLI RED, implement atomic state attachment, and run GREEN**

Run: .venv/bin/python -m pytest tests/test_initialize_csi300_paper_validation_script.py -q

Expected before implementation: script missing. Expected after implementation: pass and account bytes unchanged.

- [ ] **Step 7: Commit Task 1**

    git add src/fintech_quant/execution/paper_evidence.py src/fintech_quant/execution/__init__.py scripts/initialize_csi300_paper_validation.py tests/test_paper_evidence.py tests/test_initialize_csi300_paper_validation_script.py
    git commit -m "feat: anchor CSI300 paper validation evidence"

### Task 2: Atomic V2 cycle manifest and paper-cost parity

**Files:**
- Modify: scripts/run_daily_paper_trading.py
- Modify: scripts/run_post_close_daily_cycle.py
- Modify: tests/test_daily_paper_trading_script.py
- Modify: tests/test_run_post_close_daily_cycle_script.py

**Interfaces:**
- Both paper CLIs default to slippage_rate=0.0005.
- V2 mode requires --evidence-parent, --current-universe, and --benchmark together.
- V2 binds verified inputs, approved policy, parent, account hashes, and outputs.
- Legacy calls without V2 arguments remain V1 but never count.

- [ ] **Step 1: Add RED tests for slippage and V2 payload**

    def test_default_paper_buy_uses_five_basis_point_slippage(tmp_path: Path) -> None:
        completed, report = run_one_buy_without_slippage_argument(tmp_path, open_price=10.0)
        assert completed.returncode == 0, completed.stderr
        assert report["trades"][0]["price"] == 10.005

    def test_v2_cycle_binds_parent_inputs_policy_and_account(tmp_path: Path) -> None:
        paths = write_v2_cycle_fixture(tmp_path)
        completed = run_cycle(paths, evidence_parent=paths.anchor)
        assert completed.returncode == 0, completed.stderr
        payload = json.loads(paths.cycle_manifest.read_text())
        assert payload["schema_version"] == 2
        assert payload["kind"] == "paper_trading_cycle"
        assert payload["evidence_parent"]["sha256"] == sha256_file(paths.anchor)
        assert payload["inputs"]["research_report"]["sha256"] == sha256_file(
            paths.research_report
        )
        assert payload["policy"] == approved_paper_policy()
        account = json.loads(paths.paper_report.read_text())["account"]
        assert canonical_json_sha256(account) == payload["account_after_sha256"]

- [ ] **Step 2: Run RED**

Run: .venv/bin/python -m pytest tests/test_daily_paper_trading_script.py tests/test_run_post_close_daily_cycle_script.py -q

Expected: trade price remains 10.0 and V2 fields are missing.

- [ ] **Step 3: Implement explicit cost parity and V2 staging**

Add these arguments:

    parser.add_argument("--evidence-parent", default=None)
    parser.add_argument("--current-universe", default=None)
    parser.add_argument("--benchmark", default=None)
    parser.add_argument("--slippage-rate", type=float, default=0.0005)

When any V2 argument is present, require all three, reject --dqn-report, verify every input, and require all runtime policy arguments to equal approved_paper_policy(). Build the V2 manifest and verify the staged paper-report account before canonical replacement.

- [ ] **Step 4: Add RED rollback and DQN tests**

    def test_v2_rejects_dqn_and_preserves_account(tmp_path: Path) -> None:
        paths = write_v2_cycle_fixture(tmp_path)
        before = paths.account.read_bytes()
        completed = run_cycle(
            paths, evidence_parent=paths.anchor, dqn_report=paths.dqn_report
        )
        assert completed.returncode != 0
        assert paths.account.read_bytes() == before
        assert not paths.cycle_manifest.exists()

- [ ] **Step 5: Run focused GREEN**

Run: .venv/bin/python -m pytest tests/test_daily_paper_trading_script.py tests/test_run_post_close_daily_cycle_script.py tests/test_paper_trading_loop.py -q

Expected: all pass.

- [ ] **Step 6: Commit Task 2**

    git add scripts/run_daily_paper_trading.py scripts/run_post_close_daily_cycle.py tests/test_daily_paper_trading_script.py tests/test_run_post_close_daily_cycle_script.py
    git commit -m "feat: commit V2 paper cycle evidence"

### Task 3: CSI 300 evidence-parent orchestration

**Files:**
- Modify: scripts/run_csi300_post_close.py
- Modify: tests/test_run_csi300_post_close_script.py

**Interfaces:**
- Pipeline state must contain a verified validation_anchor.
- First cycle chains to the anchor; later cycles chain to cycle_manifest.
- The atomic cycle receives current universe, benchmark, explicit 0.0005 slippage, and parent.
- New state preserves anchor and exact V2 cycle reference.

- [ ] **Step 1: Add orchestration RED tests**

    def test_first_v2_cycle_chains_to_validation_anchor(tmp_path: Path) -> None:
        config = _config(tmp_path)
        state = _seed_state(config, date(2026, 1, 2), with_validation_anchor=True)
        runner = RecordingRunner(config)
        run_pipeline(config, runner=runner)
        command = runner.command("run_post_close_daily_cycle.py")
        assert _argument(command, "--evidence-parent") == state["validation_anchor"]["path"]
        assert _argument(command, "--slippage-rate") == "0.0005"
        new_state = json.loads(config.state.read_text())
        assert new_state["validation_anchor"] == state["validation_anchor"]

    def test_pipeline_rejects_missing_validation_anchor_before_fetch(tmp_path: Path) -> None:
        config = _config(tmp_path)
        _seed_state(config, date(2026, 1, 2), with_validation_anchor=False)
        runner = RecordingRunner(config)
        with pytest.raises(ValueError, match="validation anchor"):
            run_pipeline(config, runner=runner)
        assert runner.calls == []

- [ ] **Step 2: Run RED**

Run: .venv/bin/python -m pytest tests/test_run_csi300_post_close_script.py -q

Expected: missing anchor is accepted and V2 arguments are absent.

- [ ] **Step 3: Implement verified reference resolution**

    def _verified_reference(state: Mapping[str, object], key: str) -> Path:
        value = state.get(key)
        if not isinstance(value, Mapping):
            raise ValueError(f"pipeline state is missing {key.replace('_', ' ')}")
        path = Path(str(value.get("path", ""))).resolve()
        if value.get("sha256") != sha256_file(path):
            raise ValueError(f"pipeline state {key} hash mismatch")
        return path

Resolve anchor before any fetch. Use the prior cycle when present, otherwise the anchor. Pass V2 arguments and preserve both references in new state.

- [ ] **Step 4: Run GREEN and idempotence regressions**

Run: .venv/bin/python -m pytest tests/test_run_csi300_post_close_script.py tests/test_run_post_close_daily_cycle_script.py -q

Expected: all pass and same-date replay leaves account unchanged.

- [ ] **Step 5: Commit Task 3**

    git add scripts/run_csi300_post_close.py tests/test_run_csi300_post_close_script.py
    git commit -m "feat: chain CSI300 daily paper evidence"

### Task 4: Deterministic eight-week auditor

**Files:**
- Create: src/fintech_quant/reports/paper_validation.py
- Modify: src/fintech_quant/reports/__init__.py
- Create: scripts/audit_csi300_paper_validation.py
- Create: tests/test_paper_validation.py
- Create: tests/test_audit_csi300_paper_validation_script.py

**Interfaces:**
- Produces audit_paper_validation(anchor: Path, cycle_manifests: Sequence[Path], *, minimum_sessions: int = 40, minimum_calendar_days: int = 56, maximum_drawdown: float = 0.10) -> dict[str, object].
- Statuses are NO_EVIDENCE, COLLECTING, FAILED, ELIGIBLE_FOR_REVIEW.
- CLI discovers only cycles/*/cycle_manifest.json and writes deterministic JSON.

- [ ] **Step 1: Write RED tests for empty evidence and broken chains**

    def test_audit_reports_no_evidence_for_anchor_only(tmp_path: Path) -> None:
        anchor = write_anchor(tmp_path, as_of=date(2026, 1, 2), equity=100000.0)
        report = audit_paper_validation(anchor, [])
        assert report["status"] == "NO_EVIDENCE"
        assert report["gates"]["live_trading_disabled"]["passed"] is True

    def test_audit_rejects_broken_account_chain(tmp_path: Path) -> None:
        anchor = write_anchor(tmp_path, as_of=date(2026, 1, 2), equity=100000.0)
        cycles = write_cycle_series(tmp_path, anchor, session_count=2)
        mutate_manifest(cycles[1], account_before_sha256="wrong")
        with pytest.raises(ValueError, match="account hash chain"):
            audit_paper_validation(anchor, cycles)

- [ ] **Step 2: Run RED**

Run: .venv/bin/python -m pytest tests/test_paper_validation.py -q

Expected: module import fails.

- [ ] **Step 3: Implement core metric and gate helpers**

    def _maximum_drawdown(equities: Sequence[float]) -> float:
        peak = equities[0]
        result = 0.0
        for equity in equities:
            peak = max(peak, equity)
            result = max(result, (peak - equity) / peak if peak else 0.0)
        return result

    def _gate(passed: bool, observed: object, required: object) -> dict[str, object]:
        return {"passed": passed, "observed": observed, "required": required}

Verify all file references, V2 schema/kind, parents, account chain, embedded account, fixed policy, health, nested decision inputs, current universe, and allowed block reasons. Derive expected sessions from the latest verified benchmark and compute paper/benchmark return, excess, drawdown, turnover, costs, and counts.

- [ ] **Step 4: Add RED boundary tests**

    @pytest.mark.parametrize(
        ("sessions", "span_days", "expected_status"),
        [(39, 56, "COLLECTING"), (40, 55, "COLLECTING"),
         (40, 56, "ELIGIBLE_FOR_REVIEW")],
    )
    def test_duration_boundaries(
        tmp_path: Path, sessions: int, span_days: int, expected_status: str
    ) -> None:
        anchor, cycles = write_passing_series(
            tmp_path, sessions=sessions, span_days=span_days
        )
        assert audit_paper_validation(anchor, cycles)["status"] == expected_status

    def test_completed_window_above_ten_percent_drawdown_fails(tmp_path: Path) -> None:
        anchor, cycles = write_passing_series(
            tmp_path, sessions=40, span_days=56, drawdown=0.1001
        )
        report = audit_paper_validation(anchor, cycles)
        assert report["status"] == "FAILED"
        assert report["gates"]["maximum_drawdown"]["passed"] is False

    def test_completed_window_without_positive_excess_fails(tmp_path: Path) -> None:
        anchor, cycles = write_passing_series(
            tmp_path, sessions=40, span_days=56, paper_return=0.01,
            benchmark_return=0.02,
        )
        report = audit_paper_validation(anchor, cycles)
        assert report["status"] == "FAILED"
        assert report["gates"]["positive_excess_return"]["passed"] is False

    @pytest.mark.parametrize(
        ("mutation", "message"),
        [
            ({"data_health_passed": False}, "data health"),
            ({"dqn_exposure_enabled": True}, "DQN exposure"),
            ({"live_trading_enabled": True}, "live trading"),
            ({"blocked_reason": "missing_price"}, "execution anomaly"),
            ({"walk_forward_excess": [0.1, -0.01, 0.2, 0.1]}, "walk-forward"),
        ],
    )
    def test_mandatory_integrity_and_strategy_gates_fail(
        tmp_path: Path, mutation: dict[str, object], message: str
    ) -> None:
        anchor, cycles = write_passing_series(
            tmp_path, sessions=40, span_days=56, **mutation
        )
        report = audit_paper_validation(anchor, cycles)
        assert report["status"] == "FAILED"
        assert message in " ".join(report["failures"])

- [ ] **Step 5: Run unit GREEN**

Run: .venv/bin/python -m pytest tests/test_paper_validation.py -q

Expected: all pass.

- [ ] **Step 6: Write CLI RED, implement CLI, and run GREEN**

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/audit_csi300_paper_validation.py",
            "--anchor", str(anchor),
            "--cycle-root", str(cycle_root),
            "--output", str(output),
        ],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_text())["status"] == "COLLECTING"
    assert "live_trading_enabled=false" in completed.stdout

Run: .venv/bin/python -m pytest tests/test_audit_csi300_paper_validation_script.py -q

Expected: pass; integrity errors return non-zero.

- [ ] **Step 7: Commit Task 4**

    git add src/fintech_quant/reports/paper_validation.py src/fintech_quant/reports/__init__.py scripts/audit_csi300_paper_validation.py tests/test_paper_validation.py tests/test_audit_csi300_paper_validation_script.py
    git commit -m "feat: audit CSI300 paper readiness gates"

### Task 5: Post-cycle audit and operating contract

**Files:**
- Modify: scripts/run_csi300_post_close.py
- Modify: tests/test_run_csi300_post_close_script.py
- Modify: README.md
- Modify: AGENTS.md

**Interfaces:**
- Top-level CLI runs audit after successful state commit and on verified same-date replay.
- Default output is <cycle_dir>/validation_report.json.
- A monitoring failure never erases committed paper execution; it remains visible and non-eligible.

- [ ] **Step 1: Add RED post-commit audit tests**

    def test_pipeline_audits_after_state_commit(tmp_path: Path) -> None:
        config = _config(tmp_path)
        _seed_state(config, date(2026, 1, 2), with_validation_anchor=True)
        runner = RecordingRunner(config)
        result = run_pipeline(config, runner=runner)
        assert runner.script_names()[-1] == "audit_csi300_paper_validation.py"
        assert result["validation_status"] == "COLLECTING"

    def test_audit_failure_does_not_erase_committed_cycle(tmp_path: Path) -> None:
        config = _config(tmp_path)
        _seed_state(config, date(2026, 1, 2), with_validation_anchor=True)
        runner = RecordingRunner(config, fail_on="audit_csi300_paper_validation.py")
        with pytest.raises(subprocess.CalledProcessError):
            run_pipeline(config, runner=runner)
        assert json.loads(config.account.read_text())["last_processed_date"] == "2026-01-05"
        assert json.loads(config.state.read_text())["last_successful_as_of"] == "2026-01-05"

- [ ] **Step 2: Run RED, implement post-commit audit, and run GREEN**

Run: .venv/bin/python -m pytest tests/test_run_csi300_post_close_script.py -q

Expected before implementation: auditor absent. Expected after: all pass.

- [ ] **Step 3: Document anchor, V2, statuses, costs, paths, and prohibitions**

README documents the exact anchor command, daily command, audit command/statuses, 0.0005 slippage, and operational failure boundaries. AGENTS records implementation status and keeps the evidence clock at zero until a fresh V2 cycle succeeds.

- [ ] **Step 4: Run focused end-to-end fixtures**

Run: .venv/bin/python -m pytest tests/test_run_post_close_daily_cycle_script.py tests/test_run_csi300_post_close_script.py tests/test_audit_csi300_paper_validation_script.py -q

Expected: D queues, D+1 executes, manifests chain, replay is idempotent, and audit is COLLECTING without duplicate trades.

- [ ] **Step 5: Commit Task 5**

    git add scripts/run_csi300_post_close.py tests/test_run_csi300_post_close_script.py README.md AGENTS.md
    git commit -m "feat: operate CSI300 V2 paper validation"

### Task 6: Review, real anchor, merge, and automation switch

**Runtime outputs:**
- data/paper/csi300_baseline/validation/anchor-20260713/
- data/paper/csi300_baseline/pipeline_state.json
- outputs/paper_trading/csi300_baseline/cycles/<date>/validation_report.json

- [ ] **Step 1: Run complete feature-branch verification**

    .venv/bin/python -m pytest -q
    .venv/bin/python -m compileall -q src scripts tests
    .venv/bin/python scripts/initialize_csi300_paper_validation.py --help >/dev/null
    .venv/bin/python scripts/audit_csi300_paper_validation.py --help >/dev/null
    .venv/bin/python scripts/run_csi300_post_close.py --help >/dev/null
    git diff --check
    git status --short

Expected: all pass; only intended changes.

- [ ] **Step 2: Self-review every changed line**

Check V1 non-counting, hash completeness, account continuity, policy parity, audit math, atomic boundaries, DQN/live rejection, and unrelated edits. Every fix starts with a reproducing RED test.

- [ ] **Step 3: Push, fast-forward merge, and push main**

    git push origin codex/csi300-paper-evidence-v2
    git -C /Users/yakou/Desktop/Vibe-Trading pull --ff-only origin main
    git -C /Users/yakou/Desktop/Vibe-Trading merge --ff-only codex/csi300-paper-evidence-v2
    git -C /Users/yakou/Desktop/Vibe-Trading push origin main

- [ ] **Step 4: Re-run Step 1 on main and verify main == origin/main**

Expected: full verification passes at the pushed SHA.

- [ ] **Step 5: Create the real non-counted anchor from merged main**

    .venv/bin/python scripts/initialize_csi300_paper_validation.py \
      --account data/paper/csi300_baseline/account.json \
      --state data/paper/csi300_baseline/pipeline_state.json \
      --formal-run-manifest outputs/csi300_research/hfq-formal-20260713/manifest.json \
      --comparison outputs/csi300_research/hfq-formal-20260713/benchmark_comparison.json \
      --benchmark data/diagnostics/csi300_market_state_sina_20200601_20260713.csv \
      --output-root data/paper/csi300_baseline/validation

Run auditor with no cycles. Expected: NO_EVIDENCE, zero sessions, live disabled.

- [ ] **Step 6: Update the existing csi300 automation**

Keep weekdays 17:30 Asia/Shanghai. Require V2 manifest, validation report, 0.0005 slippage, baseline only, and ELIGIBLE_FOR_REVIEW as the strongest result. Preserve live/DQN prohibition.

- [ ] **Step 7: Execute the first eligible fresh session or wait safely**

If the market has closed and fresh data exist, run the fixed command once and verify V2/account/audit. Otherwise leave account/state unchanged and automation active for 17:30.
