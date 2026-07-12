from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_run_artifact_store_refuses_to_overwrite_raw_artifact(tmp_path: Path) -> None:
    from fintech_quant.data.run_artifacts import RunArtifactStore

    store = RunArtifactStore(tmp_path, "run-1", layer="raw")
    store.write_jsonl("fundamentals/000001.SZ.jsonl", [{"value": 1}])

    with pytest.raises(FileExistsError):
        store.write_jsonl("fundamentals/000001.SZ.jsonl", [{"value": 2}])


def test_run_artifact_manifest_records_hashes_rows_and_environment(tmp_path: Path) -> None:
    from fintech_quant.data.run_artifacts import RunArtifactStore, sha256_file

    store = RunArtifactStore(tmp_path, "run-1", layer="raw")
    artifact_path = store.write_jsonl(
        "fundamentals/000001.SZ.jsonl",
        [{"value": 1}, {"value": 2}],
    )
    manifest_path = store.write_manifest(
        request={"start": "2026-01-01", "end": "2026-06-30"},
        scopes=[{"symbol": "000001.SZ", "group": "fundamentals", "status": "success"}],
        created_at="2026-07-10T12:00:00+08:00",
        git_sha="abc123",
        provider_versions={"akshare": "fixture"},
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact = manifest["artifacts"][0]
    assert manifest["run_id"] == "run-1"
    assert manifest["layer"] == "raw"
    assert manifest["git_sha"] == "abc123"
    assert manifest["python_version"]
    assert artifact["path"] == "fundamentals/000001.SZ.jsonl"
    assert artifact["row_count"] == 2
    assert artifact["sha256"] == sha256_file(artifact_path)
