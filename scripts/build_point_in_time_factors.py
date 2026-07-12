from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.data.factor_store import (  # noqa: E402
    CAPITAL_FLOW_FIELDS,
    FUNDAMENTAL_FIELDS,
    capital_flow_row,
    fundamental_row,
    materialize_capital_flow,
    materialize_fundamentals,
)
from fintech_quant.data.run_artifacts import RunArtifactStore, sha256_file  # noqa: E402
from fintech_quant.data.price_volume_flow import materialize_price_volume_flow_proxy  # noqa: E402
from fintech_quant.information import InformationRepository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build normalized point-in-time factor tables from a raw run.")
    parser.add_argument("--raw-manifest", required=True)
    parser.add_argument("--trading-calendar", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--processed-root", default="data/processed/runs")
    parser.add_argument("--created-at", default=None)
    parser.add_argument(
        "--capital-flow-mode",
        choices=("real", "price-volume-proxy"),
        default="real",
    )
    parser.add_argument("--price-features", default=None)
    parser.add_argument("--price-volume-window", type=int, default=20)
    args = parser.parse_args()

    raw_manifest_path = Path(args.raw_manifest).resolve()
    raw_manifest = json.loads(raw_manifest_path.read_text(encoding="utf-8"))
    if raw_manifest.get("layer") != "raw":
        raise SystemExit("--raw-manifest must describe a raw run")
    records_by_group = _load_verified_records(raw_manifest_path, raw_manifest)
    trading_calendar_path = Path(args.trading_calendar).resolve()
    trading_dates = _load_trading_dates(trading_calendar_path)
    source_fetched_at = str(raw_manifest["created_at"])
    fundamentals = materialize_fundamentals(
        records_by_group["fundamentals"] + records_by_group["financial_statements"],
        source_fetched_at=source_fetched_at,
    )
    price_features_path: Path | None = None
    if args.capital_flow_mode == "price-volume-proxy":
        if not args.price_features:
            raise SystemExit("--price-features is required for price-volume-proxy mode")
        price_features_path = Path(args.price_features).resolve()
        capital_flow = materialize_price_volume_flow_proxy(
            _load_price_rows(price_features_path),
            window=args.price_volume_window,
            source_fetched_at=source_fetched_at,
        )
    else:
        capital_flow = materialize_capital_flow(
            records_by_group["capital_flow"],
            trading_dates=trading_dates,
            source_fetched_at=source_fetched_at,
        )

    store = RunArtifactStore(
        Path(args.processed_root),
        args.run_id,
        layer="processed",
        parent_manifest=str(raw_manifest_path),
    )
    store.write_csv(
        "fundamentals.csv",
        (fundamental_row(row) for row in fundamentals),
        fieldnames=FUNDAMENTAL_FIELDS,
    )
    store.write_csv(
        "capital_flow.csv",
        (capital_flow_row(row) for row in capital_flow),
        fieldnames=CAPITAL_FLOW_FIELDS,
    )
    manifest_path = store.write_manifest(
        request={
            "parent_run_id": raw_manifest.get("run_id"),
            "parent_manifest_sha256": sha256_file(raw_manifest_path),
            "trading_calendar": str(trading_calendar_path),
            "trading_calendar_sha256": sha256_file(trading_calendar_path),
            "capital_flow_mode": args.capital_flow_mode,
            "price_features": str(price_features_path) if price_features_path else None,
            "price_features_sha256": sha256_file(price_features_path) if price_features_path else None,
            "price_volume_window": args.price_volume_window if price_features_path else None,
        },
        scopes=[
            {"group": "fundamentals", "status": "success", "row_count": len(fundamentals)},
            {
                "group": "capital_flow",
                "status": "success",
                "row_count": len(capital_flow),
                "mode": args.capital_flow_mode,
            },
        ],
        created_at=args.created_at or datetime.now(timezone.utc).isoformat(),
        git_sha=_git_sha(),
        provider_versions={"raw_run": str(raw_manifest.get("run_id", ""))},
    )
    print(f"manifest={manifest_path}")
    print(f"fundamental_rows={len(fundamentals)}")
    print(f"capital_flow_rows={len(capital_flow)}")
    return 0


def _load_verified_records(
    manifest_path: Path,
    manifest: dict[str, object],
) -> dict[str, list[object]]:
    result: dict[str, list[object]] = {
        "fundamentals": [],
        "financial_statements": [],
        "capital_flow": [],
    }
    artifacts = manifest.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise ValueError("raw manifest artifacts must be a list")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        relative = str(artifact.get("path", ""))
        group = relative.split("/", 1)[0]
        if group not in result:
            continue
        path = (manifest_path.parent / relative).resolve()
        if manifest_path.parent not in path.parents:
            raise ValueError("raw artifact path escapes the raw run")
        if sha256_file(path) != artifact.get("sha256"):
            raise ValueError(f"raw artifact hash mismatch: {relative}")
        result[group].extend(InformationRepository(path).all_records())
    return result


def _load_trading_dates(path: Path) -> tuple[date, ...]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    dates = {
        date.fromisoformat(str(row.get("trade_date", "")))
        for row in rows
        if row.get("trade_date")
    }
    if not dates:
        raise ValueError("trading calendar must contain trade_date rows")
    return tuple(sorted(dates))


def _load_price_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {"symbol", "trade_date", "high", "low", "close", "volume"}
    missing = sorted(required - set(rows[0] if rows else ()))
    if missing:
        raise ValueError(f"price features missing required column: {missing[0]}")
    return rows


def _git_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
