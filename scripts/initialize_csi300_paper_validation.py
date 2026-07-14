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
    args = parser.parse_args()

    state_path = Path(args.state).resolve()
    state = _load_json(state_path)
    if state.get("validation_anchor") is not None:
        raise ValueError("pipeline state already contains a validation anchor")
    account = Path(args.account).resolve()
    account_before = account.read_bytes()
    manifest: Path | None = None
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
        )
        load_verified_anchor(manifest)
        _write_json_atomic(
            state_path,
            {**state, "validation_anchor": file_reference(manifest)},
        )
        if account.read_bytes() != account_before:
            raise ValueError("validation anchor initialization mutated the paper account")
    except BaseException:
        if manifest is not None:
            shutil.rmtree(manifest.parent, ignore_errors=True)
        raise

    print(f"anchor_manifest={manifest}")
    print(f"pipeline_state={state_path}")
    print("counts_toward_evidence=false")
    print("live_trading_enabled=false")
    return 0


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
