from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.data.corporate_action_store import (  # noqa: E402
    materialize_cninfo_corporate_actions,
)
from fintech_quant.data.run_artifacts import RunArtifactStore, sha256_file  # noqa: E402


FIELDS = ("symbol", "ex_date", "cash_dividend_per_share", "share_multiplier", "source")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build normalized corporate-action ledger.")
    parser.add_argument("--raw-manifest", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--processed-root", default="data/processed/corporate-action-runs")
    parser.add_argument("--created-at", default=None)
    args = parser.parse_args()

    raw_manifest_path = Path(args.raw_manifest).resolve()
    manifest = json.loads(raw_manifest_path.read_text(encoding="utf-8"))
    if manifest.get("layer") != "raw":
        raise SystemExit("--raw-manifest must describe a raw run")
    request = manifest.get("request", {})
    if not isinstance(request, Mapping):
        raise ValueError("raw manifest request must be an object")
    start = date.fromisoformat(str(request["start"]))
    end = date.fromisoformat(str(request["end"]))
    actions = materialize_cninfo_corporate_actions(
        _verified_rows(raw_manifest_path, manifest),
        start=start,
        end=end,
    )
    store = RunArtifactStore(
        Path(args.processed_root),
        args.run_id,
        layer="processed",
        parent_manifest=str(raw_manifest_path),
    )
    store.write_csv(
        "corporate_actions.csv",
        (
            {
                "symbol": action.symbol,
                "ex_date": action.ex_date.isoformat(),
                "cash_dividend_per_share": action.cash_dividend_per_share,
                "share_multiplier": action.share_multiplier,
                "source": action.source,
            }
            for action in actions
        ),
        fieldnames=FIELDS,
    )
    output = store.write_manifest(
        request={
            "parent_manifest_sha256": sha256_file(raw_manifest_path),
            "membership": request.get("membership"),
            "membership_sha256": request.get("membership_sha256"),
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        scopes=[{"group": "corporate_actions", "status": "success", "row_count": len(actions)}],
        created_at=args.created_at or datetime.now(timezone.utc).isoformat(),
        git_sha=_git_sha(),
        provider_versions={"raw_corporate_action_run": str(manifest.get("run_id", ""))},
    )
    print(f"manifest={output}")
    print(f"corporate_action_rows={len(actions)}")
    return 0


def _verified_rows(
    manifest_path: Path,
    manifest: Mapping[str, object],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    artifacts = manifest.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise ValueError("raw manifest artifacts must be a list")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        relative = str(artifact.get("path", ""))
        if not relative.startswith("corporate_actions/"):
            continue
        path = (manifest_path.parent / relative).resolve()
        if manifest_path.parent not in path.parents:
            raise ValueError("raw artifact path escapes the raw run")
        if sha256_file(path) != artifact.get("sha256"):
            raise ValueError(f"raw artifact hash mismatch: {relative}")
        with path.open(encoding="utf-8") as handle:
            result.extend(json.loads(line) for line in handle if line.strip())
    return result


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
