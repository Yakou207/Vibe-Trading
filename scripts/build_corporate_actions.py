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
from fintech_quant.data.manifest_chain import (  # noqa: E402
    VerifiedManifest,
    load_verified_manifest_chain,
)
from fintech_quant.data.run_artifacts import RunArtifactStore, sha256_file  # noqa: E402


FIELDS = (
    "symbol",
    "ex_date",
    "action_type",
    "cash_dividend_per_share",
    "share_multiplier",
    "rights_ratio",
    "rights_price",
    "listing_date",
    "source",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build normalized corporate-action ledger.")
    parser.add_argument("--raw-manifest", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--processed-root", default="data/processed/corporate-action-runs")
    parser.add_argument("--created-at", default=None)
    args = parser.parse_args()

    raw_manifest_path = Path(args.raw_manifest).resolve()
    chain = load_verified_manifest_chain(raw_manifest_path, expected_layer="raw")
    manifest = chain[-1].payload
    request = manifest.get("request", {})
    if not isinstance(request, Mapping):
        raise ValueError("raw manifest request must be an object")
    requests = [_request(item) for item in chain]
    start = min(date.fromisoformat(str(item["start"])) for item in requests)
    end = max(date.fromisoformat(str(item["end"])) for item in requests)
    actions_by_key = {}
    for verified in chain:
        for action in materialize_cninfo_corporate_actions(
            _verified_rows(verified),
            start=start,
            end=end,
        ):
            actions_by_key[(action.symbol, action.ex_date, action.action_type)] = action
    actions = sorted(actions_by_key.values(), key=lambda item: (item.ex_date, item.symbol))
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
                "action_type": action.action_type,
                "cash_dividend_per_share": action.cash_dividend_per_share,
                "share_multiplier": action.share_multiplier,
                "rights_ratio": action.rights_ratio,
                "rights_price": action.rights_price,
                "listing_date": (action.listing_date.isoformat() if action.listing_date else ""),
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
            "action_types": request.get("action_types", []),
            "raw_manifest_chain": _chain_references(chain),
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
    manifest: VerifiedManifest,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for relative, path in manifest.artifacts.items():
        if not relative.startswith("corporate_actions/"):
            continue
        with path.open(encoding="utf-8") as handle:
            result.extend(json.loads(line) for line in handle if line.strip())
    return result


def _request(manifest: VerifiedManifest) -> Mapping[str, object]:
    request = manifest.payload.get("request", {})
    if not isinstance(request, Mapping):
        raise ValueError("raw manifest request must be an object")
    if not request.get("start") or not request.get("end"):
        raise ValueError("raw manifest request must contain start and end")
    return request


def _chain_references(chain: tuple[VerifiedManifest, ...]) -> list[dict[str, str]]:
    return [{"path": str(item.path), "sha256": sha256_file(item.path)} for item in chain]


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
