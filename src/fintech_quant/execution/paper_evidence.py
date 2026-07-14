from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Mapping

from fintech_quant.data.manifest_chain import (
    load_verified_manifest,
    load_verified_manifest_chain,
)
from fintech_quant.data.run_artifacts import sha256_file


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
    serialized = (
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def file_reference(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    return {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }


def verify_file_reference(reference: Mapping[str, object]) -> Path:
    raw_path = reference.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("artifact reference path is required")
    path = Path(raw_path).resolve()
    if not path.is_file():
        raise ValueError(f"artifact is missing: {path}")
    if reference.get("bytes") != path.stat().st_size:
        raise ValueError(f"artifact byte count mismatch: {path}")
    if reference.get("sha256") != sha256_file(path):
        raise ValueError(f"artifact hash mismatch: {path}")
    return path


def create_validation_anchor(
    *,
    account: Path,
    pipeline_state: Path,
    formal_run_manifest: Path,
    comparison: Path,
    benchmark: Path,
    output_root: Path,
    created_at: str,
    git_sha: str,
) -> Path:
    account_payload = _load_json(account)
    state_payload = _load_json(pipeline_state)
    account_date = account_payload.get("last_processed_date")
    state_date = state_payload.get("last_successful_as_of")
    if not isinstance(account_date, str) or account_date != state_date:
        raise ValueError("account and pipeline state dates differ")

    processed = _verify_state_manifests(state_payload)
    _require_adjust(processed["signal_price"], "hfq", label="signal")
    _require_adjust(processed["execution_price"], "none", label="execution")
    formal_payload = _load_json(formal_run_manifest)
    if formal_payload.get("data_health_passed") is not True:
        raise ValueError("formal data health did not pass")
    if formal_payload.get("dqn_overlay_status") not in {None, "diagnostic_only"}:
        raise ValueError("formal DQN overlay must remain diagnostic only")
    _verify_formal_inputs(
        formal_payload,
        signal_manifest=processed["signal_price"],
        execution_manifest=processed["execution_price"],
        benchmark=benchmark,
    )

    run_dir = output_root.resolve() / f"anchor-{account_date.replace('-', '')}"
    output_root.resolve().mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(exist_ok=False)
    try:
        snapshots = {
            "account": _copy(account, run_dir / "account.json"),
            "pipeline_state": _copy(pipeline_state, run_dir / "pipeline_state.json"),
            "formal_run_manifest": _copy(
                formal_run_manifest, run_dir / "formal_run_manifest.json"
            ),
            "comparison": _copy(comparison, run_dir / "benchmark_comparison.json"),
            "benchmark": _copy(benchmark, run_dir / "benchmark.csv"),
        }
        manifest = run_dir / "anchor_manifest.json"
        _write_json(
            manifest,
            {
                "schema_version": 1,
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
            },
        )
        load_verified_anchor(manifest)
        return manifest
    except BaseException:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise


def load_verified_anchor(path: Path) -> dict[str, object]:
    payload = _load_json(path)
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported paper validation anchor schema")
    if payload.get("kind") != "paper_validation_anchor":
        raise ValueError("paper validation anchor kind is invalid")
    if payload.get("counts_toward_evidence") is not False:
        raise ValueError("paper validation anchor must not count as evidence")
    if payload.get("policy") != approved_paper_policy():
        raise ValueError("paper validation anchor policy mismatch")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise ValueError("paper validation anchor artifacts must be an object")
    for name in (
        "account",
        "pipeline_state",
        "formal_run_manifest",
        "comparison",
        "benchmark",
    ):
        reference = artifacts.get(name)
        if not isinstance(reference, Mapping):
            raise ValueError(f"paper validation anchor is missing {name}")
        verify_file_reference(reference)
    return payload


def _verify_state_manifests(state: Mapping[str, object]) -> dict[str, Path]:
    raw_manifests = state.get("manifests")
    if not isinstance(raw_manifests, Mapping):
        raise ValueError("pipeline state manifests must be an object")
    result: dict[str, Path] = {}
    for name in ("signal_price", "execution_price", "factor", "corporate_action"):
        item = raw_manifests.get(name)
        if not isinstance(item, Mapping):
            raise ValueError(f"pipeline state is missing {name} manifests")
        raw = Path(str(item.get("raw_manifest", ""))).resolve()
        processed = Path(str(item.get("processed_manifest", ""))).resolve()
        if item.get("raw_manifest_sha256") != sha256_file(raw):
            raise ValueError(f"pipeline state {name} raw manifest hash mismatch")
        if item.get("processed_manifest_sha256") != sha256_file(processed):
            raise ValueError(f"pipeline state {name} processed manifest hash mismatch")
        load_verified_manifest_chain(raw, expected_layer="raw")
        load_verified_manifest(processed, expected_layer="processed")
        result[name] = processed
    return result


def _require_adjust(path: Path, expected: str, *, label: str) -> None:
    manifest = load_verified_manifest(path, expected_layer="processed")
    request = manifest.payload.get("request")
    if not isinstance(request, Mapping) or request.get("adjust") != expected:
        raise ValueError(f"{label} manifest must set adjust={expected}")


def _verify_formal_inputs(
    formal: Mapping[str, object],
    *,
    signal_manifest: Path,
    execution_manifest: Path,
    benchmark: Path,
) -> None:
    inputs = formal.get("inputs")
    if not isinstance(inputs, Mapping):
        raise ValueError("formal run manifest inputs must be an object")
    expected = {
        "signal_price_manifest": signal_manifest.resolve(),
        "execution_price_manifest": execution_manifest.resolve(),
        "benchmark": benchmark.resolve(),
    }
    for name, expected_path in expected.items():
        reference = inputs.get(name)
        if not isinstance(reference, Mapping):
            raise ValueError(f"formal run manifest is missing {name}")
        if verify_file_reference(reference) != expected_path:
            raise ValueError(f"formal run manifest {name} path mismatch")


def _anchor_equity(account: Mapping[str, object], as_of: str) -> float:
    nav_history = account.get("nav_history")
    if isinstance(nav_history, list):
        for row in reversed(nav_history):
            if isinstance(row, Mapping) and row.get("trade_date") == as_of:
                return float(row["equity"])
    positions = account.get("positions")
    if isinstance(positions, Mapping) and positions:
        raise ValueError("bootstrap account with positions requires an as-of NAV")
    return float(account["cash"])


def _drawdown_regime(account: Mapping[str, object]) -> str:
    state = account.get("drawdown_control_state")
    if not isinstance(state, Mapping):
        raise ValueError("bootstrap account is missing drawdown state")
    regime = state.get("regime")
    if not isinstance(regime, str) or not regime:
        raise ValueError("bootstrap account drawdown regime is invalid")
    return regime


def _copy(source: Path, target: Path) -> Path:
    with source.resolve().open("rb") as source_handle, target.open("xb") as target_handle:
        shutil.copyfileobj(source_handle, target_handle)
    return target


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
