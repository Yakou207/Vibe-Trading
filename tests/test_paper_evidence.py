from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from fintech_quant.data.run_artifacts import RunArtifactStore, sha256_file
from fintech_quant.execution.paper_evidence import (
    approved_paper_policy,
    create_validation_anchor,
    file_reference,
    load_verified_anchor,
    verify_file_reference,
)


@dataclass(frozen=True)
class BootstrapPaths:
    account: Path
    state: Path
    formal_manifest: Path
    comparison: Path
    benchmark: Path


def test_approved_policy_records_cost_and_exposure_boundaries() -> None:
    policy = approved_paper_policy()

    assert policy["strategy"] == "scored_multi_factor_baseline"
    assert policy["buy_threshold"] == 70.0
    assert policy["minimum_score_confidence"] == 0.8
    assert policy["maximum_position_weight"] == 0.08
    assert policy["drawdown_reduce"] == 0.08
    assert policy["drawdown_liquidate"] == 0.09
    assert policy["drawdown_validation_limit"] == 0.10
    assert policy["commission_rate"] == 0.0003
    assert policy["minimum_commission"] == 5.0
    assert policy["slippage_rate"] == 0.0005
    assert policy["signal_adjust"] == "hfq"
    assert policy["execution_adjust"] == "none"
    assert policy["rights_issue_policy"] == "do_not_subscribe"
    assert policy["dqn_exposure_enabled"] is False
    assert policy["live_trading_enabled"] is False


def test_file_reference_rejects_tampering(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.json"
    _write_json(artifact, {"value": 1})
    reference = file_reference(artifact)

    artifact.write_text(
        artifact.read_text(encoding="utf-8").replace("1", "2"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="artifact hash mismatch"):
        verify_file_reference(reference)


def test_create_anchor_copies_mutable_state_and_does_not_count(tmp_path: Path) -> None:
    paths = _write_valid_bootstrap_fixture(tmp_path)
    account_before = paths.account.read_bytes()

    manifest = create_validation_anchor(
        account=paths.account,
        pipeline_state=paths.state,
        formal_run_manifest=paths.formal_manifest,
        comparison=paths.comparison,
        benchmark=paths.benchmark,
        output_root=tmp_path / "validation",
        created_at="2026-07-14T05:00:00+00:00",
        git_sha="abc123",
    )

    payload = load_verified_anchor(manifest)
    assert payload["kind"] == "paper_validation_anchor"
    assert payload["schema_version"] == 1
    assert payload["as_of"] == "2026-07-13"
    assert payload["counts_toward_evidence"] is False
    assert payload["git_sha"] == "abc123"
    account_snapshot = verify_file_reference(payload["artifacts"]["account"])
    state_snapshot = verify_file_reference(payload["artifacts"]["pipeline_state"])
    assert account_snapshot != paths.account
    assert state_snapshot != paths.state
    assert account_snapshot.read_bytes() == account_before
    assert payload["policy"] == approved_paper_policy()

    paths.account.write_text("tampered\n", encoding="utf-8")
    paths.state.write_text("tampered\n", encoding="utf-8")

    assert load_verified_anchor(manifest)["as_of"] == "2026-07-13"


def test_create_anchor_rejects_mismatched_account_and_state_dates(tmp_path: Path) -> None:
    paths = _write_valid_bootstrap_fixture(tmp_path)
    account = json.loads(paths.account.read_text(encoding="utf-8"))
    account["last_processed_date"] = "2026-07-12"
    _write_json(paths.account, account)

    with pytest.raises(ValueError, match="account and pipeline state dates differ"):
        _create_anchor(paths, tmp_path / "validation")


def test_create_anchor_rejects_non_hfq_signal_manifest(tmp_path: Path) -> None:
    paths = _write_valid_bootstrap_fixture(tmp_path)
    state = json.loads(paths.state.read_text(encoding="utf-8"))
    signal_manifest = Path(state["manifests"]["signal_price"]["processed_manifest"])
    signal = json.loads(signal_manifest.read_text(encoding="utf-8"))
    signal["request"]["adjust"] = "qfq"
    _write_json(signal_manifest, signal)
    state["manifests"]["signal_price"]["processed_manifest_sha256"] = sha256_file(
        signal_manifest
    )
    _write_json(paths.state, state)

    with pytest.raises(ValueError, match="signal manifest must set adjust=hfq"):
        _create_anchor(paths, tmp_path / "validation")


def test_create_anchor_rejects_failed_formal_health(tmp_path: Path) -> None:
    paths = _write_valid_bootstrap_fixture(tmp_path)
    formal = json.loads(paths.formal_manifest.read_text(encoding="utf-8"))
    formal["data_health_passed"] = False
    _write_json(paths.formal_manifest, formal)

    with pytest.raises(ValueError, match="formal data health did not pass"):
        _create_anchor(paths, tmp_path / "validation")


def test_create_anchor_refuses_to_overwrite_existing_anchor(tmp_path: Path) -> None:
    paths = _write_valid_bootstrap_fixture(tmp_path)
    root = tmp_path / "validation"
    _create_anchor(paths, root)

    with pytest.raises(FileExistsError):
        _create_anchor(paths, root)


def _create_anchor(paths: BootstrapPaths, output_root: Path) -> Path:
    return create_validation_anchor(
        account=paths.account,
        pipeline_state=paths.state,
        formal_run_manifest=paths.formal_manifest,
        comparison=paths.comparison,
        benchmark=paths.benchmark,
        output_root=output_root,
        created_at="2026-07-14T05:00:00+00:00",
        git_sha="abc123",
    )


def _write_valid_bootstrap_fixture(root: Path) -> BootstrapPaths:
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
    _write_json(
        comparison,
        {
            "candidate": {"total_return": 1.0, "max_drawdown": 0.09},
            "candidate_vs_benchmark": {"CSI 300": {"excess_return": 1.1}},
            "walk_forward": [
                {"candidate_benchmark_excess_return": value}
                for value in (0.1, 0.2, 0.3, 0.4)
            ],
        },
    )
    benchmark.parent.mkdir(parents=True, exist_ok=True)
    benchmark.write_text(
        "trade_date,index_symbol,index_close\n2026-07-13,sh000300,4000\n",
        encoding="utf-8",
    )

    manifest_refs: dict[str, dict[str, str]] = {}
    for name, adjust in (
        ("signal_price", "hfq"),
        ("execution_price", "none"),
        ("factor", None),
        ("corporate_action", None),
    ):
        raw = _write_manifest(root / "runs/raw", f"{name}-raw", layer="raw")
        processed = _write_manifest(
            root / "runs/processed",
            f"{name}-processed",
            layer="processed",
            request={"adjust": adjust} if adjust else {},
        )
        manifest_refs[name] = {
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
            "manifests": manifest_refs,
        },
    )
    signal_manifest = Path(manifest_refs["signal_price"]["processed_manifest"])
    execution_manifest = Path(manifest_refs["execution_price"]["processed_manifest"])
    formal_manifest = root / "formal/manifest.json"
    _write_json(
        formal_manifest,
        {
            "run_id": "hfq-formal",
            "git_sha": "abc123",
            "data_health_passed": True,
            "dqn_overlay_status": "diagnostic_only",
            "inputs": {
                "signal_price_manifest": file_reference(signal_manifest),
                "execution_price_manifest": file_reference(execution_manifest),
                "benchmark": file_reference(benchmark),
            },
        },
    )
    return BootstrapPaths(account, state, formal_manifest, comparison, benchmark)


def _write_manifest(
    root: Path,
    run_id: str,
    *,
    layer: str,
    request: dict[str, object] | None = None,
) -> Path:
    store = RunArtifactStore(root, run_id, layer=layer)
    store.write_jsonl("rows.jsonl", [{"run_id": run_id}])
    return store.write_manifest(
        request=request or {},
        scopes=[],
        created_at="2026-07-13T17:30:00+08:00",
        git_sha="abc123",
        provider_versions={"fixture": "1"},
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
