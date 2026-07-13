from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_loads_verified_parent_chain_oldest_first(tmp_path: Path) -> None:
    from fintech_quant.data.manifest_chain import load_verified_manifest_chain

    parent = _write_run(tmp_path, "parent")
    child = _write_run(tmp_path, "child", parent=parent)

    chain = load_verified_manifest_chain(child, expected_layer="raw")

    assert [item.payload["run_id"] for item in chain] == ["parent", "child"]
    assert chain[0].artifacts["rows.jsonl"] == parent.parent / "rows.jsonl"
    assert chain[1].artifacts["rows.jsonl"] == child.parent / "rows.jsonl"


def test_rejects_tampered_parent_artifact(tmp_path: Path) -> None:
    from fintech_quant.data.manifest_chain import load_verified_manifest_chain

    parent = _write_run(tmp_path, "parent")
    child = _write_run(tmp_path, "child", parent=parent)
    (parent.parent / "rows.jsonl").write_text('{"value": "tampered"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="artifact hash mismatch: rows.jsonl"):
        load_verified_manifest_chain(child, expected_layer="raw")


def test_rejects_manifest_parent_cycle(tmp_path: Path) -> None:
    from fintech_quant.data.manifest_chain import load_verified_manifest_chain

    first = _write_run(tmp_path, "first")
    second = _write_run(tmp_path, "second", parent=first)
    payload = json.loads(first.read_text(encoding="utf-8"))
    payload["parent_manifest"] = str(second)
    first.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest parent cycle"):
        load_verified_manifest_chain(second, expected_layer="raw")


def test_rejects_wrong_manifest_layer(tmp_path: Path) -> None:
    from fintech_quant.data.manifest_chain import load_verified_manifest_chain

    manifest = _write_run(tmp_path, "processed", layer="processed")

    with pytest.raises(ValueError, match="manifest layer must be raw"):
        load_verified_manifest_chain(manifest, expected_layer="raw")


def test_load_verified_manifest_does_not_follow_a_processed_runs_raw_parent(
    tmp_path: Path,
) -> None:
    from fintech_quant.data.manifest_chain import load_verified_manifest

    raw_manifest = _write_run(tmp_path, "raw")
    processed_manifest = _write_run(
        tmp_path,
        "processed",
        parent=raw_manifest,
        layer="processed",
    )

    verified = load_verified_manifest(processed_manifest, expected_layer="processed")

    assert verified.payload["run_id"] == "processed"
    assert verified.artifacts["rows.jsonl"] == processed_manifest.parent / "rows.jsonl"


def _write_run(
    root: Path,
    run_id: str,
    *,
    parent: Path | None = None,
    layer: str = "raw",
) -> Path:
    from fintech_quant.data.run_artifacts import RunArtifactStore

    store = RunArtifactStore(
        root,
        run_id,
        layer=layer,
        parent_manifest=str(parent) if parent else None,
    )
    store.write_jsonl("rows.jsonl", [{"value": run_id}])
    return store.write_manifest(
        request={"start": "2026-01-01", "end": "2026-01-02"},
        scopes=[],
        created_at="2026-01-02T17:30:00+08:00",
        git_sha="abc123",
        provider_versions={"fixture": "1"},
    )
