from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from fintech_quant.data.run_artifacts import RunArtifactStore, sha256_file
from fintech_quant.execution.paper_evidence import file_reference


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


def _run(paths: dict[str, Path], output_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
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
        ],
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
