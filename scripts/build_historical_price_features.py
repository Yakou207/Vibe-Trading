from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.data.base import normalize_daily_bar  # noqa: E402
from fintech_quant.data.research_dataset import (  # noqa: E402
    DAILY_BAR_FIELDS,
    OUTPUT_FEATURE_FIELDS,
)
from fintech_quant.data.run_artifacts import RunArtifactStore, sha256_file  # noqa: E402
from fintech_quant.features import enrich_daily_bars  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify immutable raw prices and build daily technical features."
    )
    parser.add_argument("--raw-manifest", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--processed-root", default="data/processed/price-runs")
    parser.add_argument("--created-at", default=None)
    args = parser.parse_args()

    raw_manifest_path = Path(args.raw_manifest).resolve()
    raw_manifest = json.loads(raw_manifest_path.read_text(encoding="utf-8"))
    if raw_manifest.get("layer") != "raw":
        raise SystemExit("--raw-manifest must describe a raw run")
    rows = _verified_price_rows(raw_manifest_path, raw_manifest)
    features = enrich_daily_bars(rows)
    store = RunArtifactStore(
        Path(args.processed_root),
        args.run_id,
        layer="processed",
        parent_manifest=str(raw_manifest_path),
    )
    store.write_csv("daily.csv", rows, fieldnames=DAILY_BAR_FIELDS)
    store.write_csv("features.csv", features, fieldnames=OUTPUT_FEATURE_FIELDS)
    request = raw_manifest.get("request", {})
    if not isinstance(request, Mapping):
        raise ValueError("raw manifest request must be an object")
    manifest = store.write_manifest(
        request={
            "parent_manifest_sha256": sha256_file(raw_manifest_path),
            "membership": request.get("membership"),
            "membership_sha256": request.get("membership_sha256"),
            "start": request.get("start"),
            "end": request.get("end"),
        },
        scopes=[
            {"group": "daily", "status": "success", "row_count": len(rows)},
            {"group": "features", "status": "success", "row_count": len(features)},
        ],
        created_at=args.created_at or datetime.now(timezone.utc).isoformat(),
        git_sha=_git_sha(),
        provider_versions={"raw_price_run": str(raw_manifest.get("run_id", ""))},
    )
    print(f"manifest={manifest}")
    print(f"daily_rows={len(rows)}")
    print(f"feature_rows={len(features)}")
    return 0


def _verified_price_rows(
    manifest_path: Path,
    manifest: Mapping[str, object],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    artifacts = manifest.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise ValueError("raw manifest artifacts must be a list")
    for artifact in artifacts:
        if not isinstance(artifact, dict) or not str(artifact.get("path", "")).startswith("prices/"):
            continue
        relative = str(artifact["path"])
        path = (manifest_path.parent / relative).resolve()
        if manifest_path.parent not in path.parents:
            raise ValueError("raw artifact path escapes the raw run")
        if sha256_file(path) != artifact.get("sha256"):
            raise ValueError(f"raw artifact hash mismatch: {relative}")
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                payload = json.loads(line)
                row = normalize_daily_bar(
                    str(payload["symbol"]),
                    payload,
                    str(payload.get("source", "unknown")),
                )
                key = (str(row["symbol"]), str(row["trade_date"]))
                if key in seen:
                    raise ValueError(f"duplicate raw price row: {key[0]} {key[1]}")
                seen.add(key)
                result.append(row)
    if not result:
        raise ValueError("raw run contains no price rows")
    return sorted(result, key=lambda row: (str(row["symbol"]), str(row["trade_date"])))


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
