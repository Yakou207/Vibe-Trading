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
from fintech_quant.data.manifest_chain import (  # noqa: E402
    VerifiedManifest,
    load_verified_manifest_chain,
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
    chain = load_verified_manifest_chain(raw_manifest_path, expected_layer="raw")
    raw_manifest = chain[-1].payload
    chain_requests = [_request(item) for item in chain]
    adjust_modes = {item.get("adjust") for item in chain_requests}
    if len(chain) > 1 and (None in adjust_modes or len(adjust_modes) != 1):
        raise ValueError("raw price chain mixes adjustment modes")
    rows = _verified_price_rows(chain)
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
            "start": min(str(item["start"]) for item in chain_requests),
            "end": max(str(item["end"]) for item in chain_requests),
            "adjust": request.get("adjust"),
            "raw_manifest_chain": _chain_references(chain),
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
    chain: tuple[VerifiedManifest, ...],
) -> list[dict[str, object]]:
    result: dict[tuple[str, str], dict[str, object]] = {}
    for verified in chain:
        run_rows: dict[tuple[str, str], dict[str, object]] = {}
        for relative, path in verified.artifacts.items():
            if not relative.startswith("prices/"):
                continue
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
                    if key in run_rows:
                        raise ValueError(f"duplicate raw price row: {key[0]} {key[1]}")
                    run_rows[key] = row
        result.update(run_rows)
    if not result:
        raise ValueError("raw run contains no price rows")
    return [result[key] for key in sorted(result)]


def _chain_references(chain: tuple[VerifiedManifest, ...]) -> list[dict[str, str]]:
    return [{"path": str(item.path), "sha256": sha256_file(item.path)} for item in chain]


def _request(manifest: VerifiedManifest) -> Mapping[str, object]:
    request = manifest.payload.get("request", {})
    if not isinstance(request, Mapping):
        raise ValueError("raw manifest request must be an object")
    if not request.get("start") or not request.get("end"):
        raise ValueError("raw manifest request must contain start and end")
    return request


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
