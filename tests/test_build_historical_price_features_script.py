from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path


def test_build_historical_price_features_verifies_raw_hashes_and_writes_manifest(
    tmp_path: Path,
) -> None:
    from fintech_quant.data.run_artifacts import RunArtifactStore, sha256_file

    membership = tmp_path / "membership.csv"
    membership.write_text("symbol\n000001.SZ\n", encoding="utf-8")
    raw_store = RunArtifactStore(tmp_path / "raw", "prices-1", layer="raw")
    raw_store.write_jsonl(
        "prices/000001.SZ.jsonl",
        [_bar("2026-01-02", 10.0), _bar("2026-01-05", 11.0)],
    )
    raw_manifest = raw_store.write_manifest(
        request={
            "membership": str(membership.resolve()),
            "membership_sha256": sha256_file(membership),
            "start": "2026-01-01",
            "end": "2026-01-05",
        },
        scopes=[{"symbol": "000001.SZ", "status": "success", "artifact": "prices/000001.SZ.jsonl"}],
        created_at="2026-07-11T00:00:00+08:00",
        git_sha="abc123",
        provider_versions={"fixture": "1"},
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_historical_price_features.py",
            "--raw-manifest",
            str(raw_manifest),
            "--run-id",
            "features-1",
            "--processed-root",
            str(tmp_path / "processed"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    manifest = json.loads((tmp_path / "processed/features-1/manifest.json").read_text(encoding="utf-8"))
    assert manifest["request"]["parent_manifest_sha256"] == sha256_file(raw_manifest)
    assert {artifact["path"] for artifact in manifest["artifacts"]} == {
        "daily.csv",
        "features.csv",
    }
    with (tmp_path / "processed/features-1/features.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert rows[1]["return_1d"] == "0.1"


def test_build_historical_price_features_rejects_tampered_raw_artifact(tmp_path: Path) -> None:
    from fintech_quant.data.run_artifacts import RunArtifactStore

    raw_store = RunArtifactStore(tmp_path / "raw", "prices-1", layer="raw")
    artifact = raw_store.write_jsonl("prices/000001.SZ.jsonl", [_bar("2026-01-02", 10.0)])
    raw_manifest = raw_store.write_manifest(
        request={"membership": "fixture", "membership_sha256": "fixture"},
        scopes=[],
        created_at="2026-07-11T00:00:00+08:00",
        git_sha="abc123",
        provider_versions={"fixture": "1"},
    )
    artifact.write_text("tampered\n", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_historical_price_features.py",
            "--raw-manifest",
            str(raw_manifest),
            "--run-id",
            "features-1",
            "--processed-root",
            str(tmp_path / "processed"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "raw artifact hash mismatch" in completed.stderr


def test_build_historical_price_features_merges_parent_chain_and_child_overrides(
    tmp_path: Path,
) -> None:
    from fintech_quant.data.run_artifacts import RunArtifactStore

    parent_store = RunArtifactStore(tmp_path / "raw", "parent", layer="raw")
    parent_store.write_jsonl(
        "prices/000001.SZ.jsonl",
        [_bar("2026-01-02", 10.0), _bar("2026-01-03", 10.5)],
    )
    parent_manifest = parent_store.write_manifest(
        request={"start": "2026-01-01", "end": "2026-01-03", "adjust": "qfq"},
        scopes=[],
        created_at="2026-01-03T17:30:00+08:00",
        git_sha="parent",
        provider_versions={"fixture": "1"},
    )
    child_store = RunArtifactStore(
        tmp_path / "raw",
        "child",
        layer="raw",
        parent_manifest=str(parent_manifest),
    )
    child_store.write_jsonl(
        "prices/000001.SZ.jsonl",
        [_bar("2026-01-02", 11.0), _bar("2026-01-05", 12.0)],
    )
    child_manifest = child_store.write_manifest(
        request={"start": "2026-01-02", "end": "2026-01-05", "adjust": "qfq"},
        scopes=[],
        created_at="2026-01-05T17:30:00+08:00",
        git_sha="child",
        provider_versions={"fixture": "1"},
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_historical_price_features.py",
            "--raw-manifest",
            str(child_manifest),
            "--run-id",
            "features",
            "--processed-root",
            str(tmp_path / "processed"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    with (tmp_path / "processed/features/daily.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert [(row["trade_date"], row["close"]) for row in rows] == [
        ("2026-01-02", "11.0"),
        ("2026-01-03", "10.5"),
        ("2026-01-05", "12.0"),
    ]
    manifest = json.loads(
        (tmp_path / "processed/features/manifest.json").read_text(encoding="utf-8")
    )
    assert [item["path"] for item in manifest["request"]["raw_manifest_chain"]] == [
        str(parent_manifest.resolve()),
        str(child_manifest.resolve()),
    ]
    assert manifest["request"]["start"] == "2026-01-01"
    assert manifest["request"]["end"] == "2026-01-05"


def test_build_historical_price_features_rejects_mixed_adjustment_chain(
    tmp_path: Path,
) -> None:
    from fintech_quant.data.run_artifacts import RunArtifactStore

    parent_store = RunArtifactStore(tmp_path / "raw", "parent", layer="raw")
    parent_store.write_jsonl("prices/000001.SZ.jsonl", [_bar("2026-01-02", 10.0)])
    parent_manifest = parent_store.write_manifest(
        request={"start": "2026-01-02", "end": "2026-01-02", "adjust": "qfq"},
        scopes=[],
        created_at="2026-01-02T17:30:00+08:00",
        git_sha="parent",
        provider_versions={"fixture": "1"},
    )
    child_store = RunArtifactStore(
        tmp_path / "raw",
        "child",
        layer="raw",
        parent_manifest=str(parent_manifest),
    )
    child_store.write_jsonl("prices/000001.SZ.jsonl", [_bar("2026-01-05", 12.0)])
    child_manifest = child_store.write_manifest(
        request={"start": "2026-01-05", "end": "2026-01-05", "adjust": "none"},
        scopes=[],
        created_at="2026-01-05T17:30:00+08:00",
        git_sha="child",
        provider_versions={"fixture": "1"},
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_historical_price_features.py",
            "--raw-manifest",
            str(child_manifest),
            "--run-id",
            "features",
            "--processed-root",
            str(tmp_path / "processed"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "raw price chain mixes adjustment modes" in completed.stderr


def _bar(trade_date: str, close: float) -> dict[str, object]:
    return {
        "symbol": "000001.SZ",
        "trade_date": trade_date,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 100.0,
        "amount": close * 100.0,
        "source": "fixture",
    }
