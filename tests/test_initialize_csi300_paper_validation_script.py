from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.initialize_csi300_paper_validation as initializer
from fintech_quant.data.run_artifacts import RunArtifactStore, sha256_file
from fintech_quant.execution.paper_evidence import (
    file_reference,
    load_verified_anchor,
    verify_file_reference,
)


ROOT = Path(__file__).resolve().parents[1]


def test_cli_creates_anchor_and_atomically_attaches_it_to_state(tmp_path: Path) -> None:
    paths = _bootstrap_paths(tmp_path)
    account_before = paths["account"].read_bytes()

    completed = _run(paths, tmp_path / "validation")

    assert completed.returncode == 0, completed.stderr
    assert paths["account"].read_bytes() == account_before
    state = _load_json(paths["state"])
    assert state["last_successful_as_of"] == "2026-07-13"
    anchor = Path(state["validation_anchor"]["path"])
    assert anchor.is_file()
    assert state["validation_anchor"]["sha256"] == sha256_file(anchor)
    assert f"anchor_manifest={anchor}" in completed.stdout


def test_cli_refuses_to_replace_existing_anchor_or_state_reference(tmp_path: Path) -> None:
    paths = _bootstrap_paths(tmp_path)
    root = tmp_path / "validation"
    first = _run(paths, root)
    assert first.returncode == 0, first.stderr
    state_before = paths["state"].read_bytes()

    second = _run(paths, root)

    assert second.returncode != 0
    assert paths["state"].read_bytes() == state_before


def test_cli_supersedes_existing_epoch_without_mutating_old_evidence(
    tmp_path: Path,
) -> None:
    paths = _bootstrap_paths(tmp_path)
    root = tmp_path / "validation"
    first = _run(paths, root)
    assert first.returncode == 0, first.stderr
    state = _load_json(paths["state"])
    old_anchor = Path(state["validation_anchor"]["path"])
    cycle = tmp_path / "cycles" / "2026-07-13" / "cycle_manifest.json"
    report = tmp_path / "cycles" / "2026-07-13" / "validation_report.json"
    _write_json(
        cycle,
        {
            "schema_version": 2,
            "kind": "paper_trading_cycle",
            "as_of": "2026-07-13",
            "evidence_parent": file_reference(old_anchor),
            "account_after_sha256": sha256_file(paths["account"]),
        },
    )
    _write_json(
        report,
        {
            "schema_version": 1,
            "kind": "csi300_paper_validation_report",
            "status": "FAILED",
            "live_trading_authorized": False,
            "anchor": file_reference(old_anchor),
            "latest_cycle": file_reference(cycle),
        },
    )
    for name, adjust in (("signal_price", "hfq"), ("execution_price", "none")):
        current_processed = _manifest(
            tmp_path / "runs/current-processed",
            f"{name}-current",
            "processed",
            {"adjust": adjust},
        )
        state["manifests"][name]["processed_manifest"] = str(
            current_processed.resolve()
        )
        state["manifests"][name]["processed_manifest_sha256"] = sha256_file(
            current_processed
        )
    state["cycle_manifest"] = file_reference(cycle)
    state["evidence_parent"] = file_reference(cycle)
    state["validation_report"] = file_reference(report)
    _write_json(paths["state"], state)
    old_anchor_before = old_anchor.read_bytes()
    cycle_before = cycle.read_bytes()
    report_before = report.read_bytes()

    completed = _run(paths, root, supersede=True)

    assert completed.returncode == 0, completed.stderr
    state_after = _load_json(paths["state"])
    new_anchor = Path(state_after["validation_anchor"]["path"])
    assert new_anchor != old_anchor
    assert state_after["evidence_parent"] == state_after["validation_anchor"]
    payload = load_verified_anchor(new_anchor)
    assert (
        verify_file_reference(payload["supersedes"]["validation_anchor"])
        == old_anchor.resolve()
    )
    assert (
        verify_file_reference(payload["supersedes"]["cycle_manifest"])
        == cycle.resolve()
    )
    assert (
        verify_file_reference(payload["supersedes"]["validation_report"])
        == report.resolve()
    )
    assert old_anchor.read_bytes() == old_anchor_before
    assert cycle.read_bytes() == cycle_before
    assert report.read_bytes() == report_before

    repeated = _run(paths, root, supersede=True)

    assert repeated.returncode == 0, repeated.stderr
    repeated_state = _load_json(paths["state"])
    repeated_anchor = Path(repeated_state["validation_anchor"]["path"])
    assert repeated_anchor != new_anchor
    assert repeated_state["evidence_parent"] == repeated_state["validation_anchor"]
    repeated_payload = load_verified_anchor(repeated_anchor)
    assert set(repeated_payload["supersedes"]) == {"validation_anchor"}


def test_cli_supersedes_committed_cycle_without_audit_report(tmp_path: Path) -> None:
    paths = _bootstrap_paths(tmp_path)
    root = tmp_path / "validation"
    first = _run(paths, root)
    assert first.returncode == 0, first.stderr
    state = _load_json(paths["state"])
    old_anchor = Path(state["validation_anchor"]["path"])
    cycle = tmp_path / "cycles" / "2026-07-13" / "cycle_manifest.json"
    _write_json(
        cycle,
        {
            "schema_version": 2,
            "kind": "paper_trading_cycle",
            "as_of": "2026-07-13",
            "evidence_parent": file_reference(old_anchor),
            "account_after_sha256": sha256_file(paths["account"]),
        },
    )
    state["cycle_manifest"] = file_reference(cycle)
    state["evidence_parent"] = file_reference(cycle)
    _write_json(paths["state"], state)

    completed = _run(paths, root, supersede=True)

    assert completed.returncode == 0, completed.stderr
    new_anchor = Path(_load_json(paths["state"])["validation_anchor"]["path"])
    payload = load_verified_anchor(new_anchor)
    assert set(payload["supersedes"]) == {
        "validation_anchor",
        "cycle_manifest",
    }


def test_cli_rejects_supersession_when_latest_report_targets_wrong_cycle(
    tmp_path: Path,
) -> None:
    paths = _bootstrap_paths(tmp_path)
    root = tmp_path / "validation"
    first = _run(paths, root)
    assert first.returncode == 0, first.stderr
    state = _load_json(paths["state"])
    old_anchor = Path(state["validation_anchor"]["path"])
    cycle = tmp_path / "cycles" / "2026-07-13" / "cycle_manifest.json"
    wrong_cycle = tmp_path / "cycles" / "2026-07-12" / "cycle_manifest.json"
    report = tmp_path / "cycles" / "2026-07-13" / "validation_report.json"
    for path, as_of in (
        (cycle, "2026-07-13"),
        (wrong_cycle, "2026-07-12"),
    ):
        _write_json(
            path,
            {
                "schema_version": 2,
                "kind": "paper_trading_cycle",
                "as_of": as_of,
                "evidence_parent": file_reference(old_anchor),
                "account_after_sha256": sha256_file(paths["account"]),
            },
        )
    _write_json(
        report,
        {
            "schema_version": 1,
            "kind": "csi300_paper_validation_report",
            "status": "FAILED",
            "live_trading_authorized": False,
            "anchor": file_reference(old_anchor),
            "latest_cycle": file_reference(wrong_cycle),
        },
    )
    state["cycle_manifest"] = file_reference(cycle)
    state["evidence_parent"] = file_reference(cycle)
    state["validation_report"] = file_reference(report)
    _write_json(paths["state"], state)
    state_before = paths["state"].read_bytes()

    completed = _run(paths, root, supersede=True)

    assert completed.returncode != 0
    assert "latest cycle" in completed.stderr
    assert paths["state"].read_bytes() == state_before


def test_cli_preserves_published_anchor_when_state_fsync_reports_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _bootstrap_paths(tmp_path)
    output_root = tmp_path / "validation"
    real_write = initializer._write_json_atomic

    def replace_then_fail(path: Path, payload: object) -> None:
        real_write(path, payload)
        raise OSError("directory fsync failed after replace")

    monkeypatch.setattr(initializer, "_write_json_atomic", replace_then_fail)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "initialize_csi300_paper_validation.py",
            "--account",
            str(paths["account"]),
            "--state",
            str(paths["state"]),
            "--formal-run-manifest",
            str(paths["formal_manifest"]),
            "--comparison",
            str(paths["comparison"]),
            "--benchmark",
            str(paths["benchmark"]),
            "--output-root",
            str(output_root),
            "--created-at",
            "2026-07-14T05:00:00+00:00",
        ],
    )

    with pytest.raises(OSError, match="directory fsync failed"):
        initializer.main()

    state = _load_json(paths["state"])
    anchor = Path(state["validation_anchor"]["path"])
    assert anchor.is_file()
    assert state["validation_anchor"] == file_reference(anchor)


def _run(
    paths: dict[str, Path],
    output_root: Path,
    *,
    supersede: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "scripts/initialize_csi300_paper_validation.py",
        "--account",
        str(paths["account"]),
        "--state",
        str(paths["state"]),
        "--formal-run-manifest",
        str(paths["formal_manifest"]),
        "--comparison",
        str(paths["comparison"]),
        "--benchmark",
        str(paths["benchmark"]),
        "--output-root",
        str(output_root),
        "--created-at",
        "2026-07-14T05:00:00+00:00",
    ]
    if supersede:
        command.append("--supersede-current-epoch")
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _bootstrap_paths(root: Path) -> dict[str, Path]:
    account = root / "paper/account.json"
    state = root / "paper/pipeline_state.json"
    comparison = root / "formal/benchmark_comparison.json"
    benchmark = root / "formal/benchmark.csv"
    _write_json(
        account,
        {
            "cash": 100000.0,
            "last_processed_date": "2026-07-13",
            "positions": {},
            "drawdown_control_state": {
                "actual_peak": 100000.0,
                "shadow_peak": 100000.0,
                "regime": "normal",
                "last_transition_date": None,
                "transitions": [],
            },
        },
    )
    _write_json(comparison, {"walk_forward": []})
    benchmark.parent.mkdir(parents=True, exist_ok=True)
    benchmark.write_text(
        "trade_date,index_symbol,index_close\n2026-07-13,sh000300,4000\n",
        encoding="utf-8",
    )
    manifests: dict[str, dict[str, str]] = {}
    for name, adjust in (
        ("signal_price", "hfq"),
        ("execution_price", "none"),
        ("factor", None),
        ("corporate_action", None),
    ):
        raw = _manifest(root / "runs/raw", f"{name}-raw", "raw", {})
        processed = _manifest(
            root / "runs/processed",
            f"{name}-processed",
            "processed",
            {"adjust": adjust} if adjust else {},
        )
        manifests[name] = {
            "raw_manifest": str(raw.resolve()),
            "raw_manifest_sha256": sha256_file(raw),
            "processed_manifest": str(processed.resolve()),
            "processed_manifest_sha256": sha256_file(processed),
        }
    _write_json(
        state,
        {
            "schema_version": 1,
            "last_successful_as_of": "2026-07-13",
            "manifests": manifests,
        },
    )
    formal_manifest = root / "formal/manifest.json"
    _write_json(
        formal_manifest,
        {
            "data_health_passed": True,
            "dqn_overlay_status": "diagnostic_only",
            "inputs": {
                "signal_price_manifest": file_reference(
                    Path(manifests["signal_price"]["processed_manifest"])
                ),
                "execution_price_manifest": file_reference(
                    Path(manifests["execution_price"]["processed_manifest"])
                ),
                "benchmark": file_reference(benchmark),
            },
        },
    )
    return {
        "account": account,
        "state": state,
        "comparison": comparison,
        "benchmark": benchmark,
        "formal_manifest": formal_manifest,
    }


def _manifest(
    root: Path,
    run_id: str,
    layer: str,
    request: dict[str, object],
) -> Path:
    store = RunArtifactStore(root, run_id, layer=layer)
    store.write_jsonl("rows.jsonl", [{"run_id": run_id}])
    return store.write_manifest(
        request=request,
        scopes=[],
        created_at="2026-07-13T17:30:00+08:00",
        git_sha="abc123",
        provider_versions={"fixture": "1"},
    )


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
