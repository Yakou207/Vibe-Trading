from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.execution.paper_evidence import (  # noqa: E402
    create_validation_anchor,
    file_reference,
    load_verified_anchor,
    verify_file_reference,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create the immutable non-counted CSI 300 paper-validation anchor."
    )
    parser.add_argument("--account", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--formal-run-manifest", required=True)
    parser.add_argument("--comparison", required=True)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--created-at", default=None)
    parser.add_argument("--supersede-current-epoch", action="store_true")
    args = parser.parse_args()

    state_path = Path(args.state).resolve()
    state = _load_json(state_path)
    account = Path(args.account).resolve()
    existing_anchor = state.get("validation_anchor")
    if existing_anchor is not None and not args.supersede_current_epoch:
        raise ValueError("pipeline state already contains a validation anchor")
    if existing_anchor is None and args.supersede_current_epoch:
        raise ValueError("validation epoch supersession requires an existing anchor")
    supersedes: dict[str, Mapping[str, object]] | None = None
    if args.supersede_current_epoch:
        anchor_reference = _verified_state_reference(state, "validation_anchor")
        anchor_path = verify_file_reference(anchor_reference)
        load_verified_anchor(anchor_path)
        supersedes = {
            "validation_anchor": anchor_reference,
        }
        active_parent = (
            verify_file_reference(state["evidence_parent"])
            if isinstance(state.get("evidence_parent"), Mapping)
            else verify_file_reference(state["cycle_manifest"])
            if isinstance(state.get("cycle_manifest"), Mapping)
            else anchor_path
        )
        if active_parent != anchor_path:
            if not isinstance(state.get("cycle_manifest"), Mapping):
                raise ValueError(
                    "active evidence parent is not the latest cycle manifest"
                )
            cycle_reference = _verified_latest_cycle_reference(
                state,
                account=account,
                validation_anchor=anchor_path,
            )
            if verify_file_reference(cycle_reference) != active_parent:
                raise ValueError(
                    "active evidence parent is not the latest cycle manifest"
                )
            report_reference = _optional_verified_latest_report_reference(
                state,
                validation_anchor=anchor_path,
                latest_cycle=verify_file_reference(cycle_reference),
            )
            supersedes["cycle_manifest"] = cycle_reference
            if report_reference is not None:
                supersedes["validation_report"] = report_reference
    account_before = account.read_bytes()
    manifest: Path | None = None
    state_publish_started = False
    try:
        manifest = create_validation_anchor(
            account=account,
            pipeline_state=state_path,
            formal_run_manifest=Path(args.formal_run_manifest).resolve(),
            comparison=Path(args.comparison).resolve(),
            benchmark=Path(args.benchmark).resolve(),
            output_root=Path(args.output_root).resolve(),
            created_at=args.created_at or datetime.now(timezone.utc).isoformat(),
            git_sha=_git_sha(),
            supersedes=supersedes,
        )
        load_verified_anchor(manifest)
        if account.read_bytes() != account_before:
            raise ValueError("validation anchor initialization mutated the paper account")
        anchor_reference = file_reference(manifest)
        state_publish_started = True
        _write_json_atomic(
            state_path,
            {
                **state,
                "validation_anchor": anchor_reference,
                "evidence_parent": anchor_reference,
            },
        )
    except BaseException:
        preserve_anchor = False
        if manifest is not None and state_publish_started:
            try:
                published = _load_json(state_path).get("validation_anchor")
                preserve_anchor = (
                    isinstance(published, Mapping)
                    and verify_file_reference(published) == manifest.resolve()
                )
            except BaseException:
                preserve_anchor = True
        if manifest is not None and not preserve_anchor:
            shutil.rmtree(manifest.parent, ignore_errors=True)
        raise

    print(f"anchor_manifest={manifest}")
    print(f"pipeline_state={state_path}")
    print("counts_toward_evidence=false")
    print("live_trading_enabled=false")
    return 0


def _verified_state_reference(
    state: Mapping[str, object],
    name: str,
) -> dict[str, object]:
    reference = state.get(name)
    if not isinstance(reference, Mapping):
        raise ValueError(f"pipeline state is missing {name.replace('_', ' ')}")
    verify_file_reference(reference)
    return dict(reference)


def _verified_latest_cycle_reference(
    state: Mapping[str, object],
    *,
    account: Path,
    validation_anchor: Path,
) -> dict[str, object]:
    reference = _verified_state_reference(state, "cycle_manifest")
    path = verify_file_reference(reference)
    payload = _load_json(path)
    state_date = state.get("last_successful_as_of")
    if (
        payload.get("schema_version") != 2
        or payload.get("kind") != "paper_trading_cycle"
    ):
        raise ValueError("latest cycle manifest schema is invalid")
    if not isinstance(state_date, str) or payload.get("as_of") != state_date:
        raise ValueError("latest cycle manifest date differs from pipeline state")
    if payload.get("account_after_sha256") != file_reference(account)["sha256"]:
        raise ValueError("latest cycle manifest account hash mismatch")
    parent = payload.get("evidence_parent")
    if not isinstance(parent, Mapping):
        raise ValueError("latest cycle manifest evidence parent is missing")
    parent_path = verify_file_reference(parent)
    if parent_path != validation_anchor:
        parent_payload = _load_json(parent_path)
        if (
            parent_payload.get("schema_version") != 2
            or parent_payload.get("kind") != "paper_trading_cycle"
            or str(parent_payload.get("as_of", "")) >= state_date
        ):
            raise ValueError("latest cycle manifest evidence parent is invalid")
    return reference


def _optional_verified_latest_report_reference(
    state: Mapping[str, object],
    *,
    validation_anchor: Path,
    latest_cycle: Path,
) -> dict[str, object] | None:
    if isinstance(state.get("validation_report"), Mapping):
        reference = _verified_state_reference(state, "validation_report")
    else:
        report = latest_cycle.with_name("validation_report.json")
        if not report.is_file():
            return None
        reference = file_reference(report)
    payload = _load_json(verify_file_reference(reference))
    if (
        payload.get("schema_version") != 1
        or payload.get("kind") != "csi300_paper_validation_report"
        or payload.get("status")
        not in {"NO_EVIDENCE", "COLLECTING", "FAILED", "ELIGIBLE_FOR_REVIEW"}
        or payload.get("live_trading_authorized") is not False
    ):
        raise ValueError("latest validation report schema or status is invalid")
    anchor = payload.get("anchor")
    latest = payload.get("latest_cycle")
    if not isinstance(anchor, Mapping) or verify_file_reference(anchor) != validation_anchor:
        raise ValueError("latest validation report anchor mismatch")
    if not isinstance(latest, Mapping) or verify_file_reference(latest) != latest_cycle:
        raise ValueError("latest validation report latest cycle mismatch")
    return reference


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    staged = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        staged.write_text(
            json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        with staged.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(staged, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        staged.unlink(missing_ok=True)


def _git_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
