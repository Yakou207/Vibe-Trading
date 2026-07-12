from __future__ import annotations

import argparse
import csv
import importlib.metadata
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.data.akshare_provider import AkShareProvider  # noqa: E402
from fintech_quant.data.base import normalize_daily_bar  # noqa: E402
from fintech_quant.data.run_artifacts import RunArtifactStore, sha256_file  # noqa: E402
from fintech_quant.data.symbols import normalize_a_share_symbol  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect immutable, resumable daily-price artifacts for historical members."
    )
    parser.add_argument(
        "--source",
        choices=("akshare", "akshare-sina", "akshare-tencent", "fixture"),
        default="akshare",
    )
    parser.add_argument("--fixture-input", default=None)
    parser.add_argument("--membership", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--raw-root", default="data/raw/price-runs")
    parser.add_argument("--resume-from", default=None)
    parser.add_argument("--created-at", default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--adjust", choices=("qfq", "none"), default="qfq")
    args = parser.parse_args()

    if args.source == "fixture" and not args.fixture_input:
        raise SystemExit("--fixture-input is required when --source fixture")
    if args.workers < 1:
        raise SystemExit("--workers must be positive")
    if args.source == "akshare-sina" and args.workers != 1:
        raise SystemExit("akshare-sina requires --workers 1 because its adjustment runtime is not thread-safe")
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if end < start:
        raise SystemExit("--end must not be earlier than --start")

    membership_path = Path(args.membership).resolve()
    symbols = _membership_symbols(membership_path)
    fixture = _fixture(Path(args.fixture_input)) if args.fixture_input else None
    parent_path = Path(args.resume_from).resolve() if args.resume_from else None
    parent = _parent_manifest(parent_path)
    store = RunArtifactStore(
        Path(args.raw_root),
        args.run_id,
        layer="raw",
        parent_manifest=str(parent_path) if parent_path else None,
    )
    provider = (
        AkShareProvider(
            backend={
                "akshare": "eastmoney",
                "akshare-sina": "sina",
                "akshare-tencent": "tencent",
            }[args.source],
            adjust=args.adjust,
        )
        if args.source != "fixture"
        else None
    )
    scopes: list[dict[str, object]] = []
    failed = 0
    reused = 0
    fetched = 0
    pending: list[str] = []
    for symbol in symbols:
        relative = f"prices/{symbol}.jsonl"
        parent_scope = _verified_parent_scope(parent, parent_path, symbol)
        if parent_scope is not None and parent_path is not None:
            store.copy_artifact(parent_path.parent / str(parent_scope["artifact"]), relative)
            scopes.append(
                {"symbol": symbol, "status": "reused", "artifact": relative, "error": None}
            )
            reused += 1
            continue
        pending.append(symbol)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_by_symbol = {
            executor.submit(_fetch_rows, args.source, fixture, provider, symbol, start, end): symbol
            for symbol in pending
        }
        for completed, future in enumerate(as_completed(future_by_symbol), start=1):
            symbol = future_by_symbol[future]
            relative = f"prices/{symbol}.jsonl"
            try:
                rows = future.result()
            except Exception as exc:
                scopes.append(
                    {"symbol": symbol, "status": "failed", "artifact": None, "error": str(exc)}
                )
                failed += 1
            else:
                store.write_jsonl(relative, rows)
                scopes.append(
                    {
                        "symbol": symbol,
                        "status": "success" if rows else "empty",
                        "artifact": relative,
                        "error": None,
                    }
                )
                fetched += 1
            if completed % 25 == 0 or completed == len(pending):
                print(
                    f"progress={completed}/{len(pending)} failed={failed}",
                    flush=True,
                )

    manifest = store.write_manifest(
        request={
            "source": args.source,
            "membership": str(membership_path),
            "membership_sha256": sha256_file(membership_path),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "adjust": args.adjust,
            "symbols": list(symbols),
        },
        scopes=sorted(scopes, key=lambda scope: str(scope["symbol"])),
        created_at=args.created_at or datetime.now(timezone.utc).isoformat(),
        git_sha=_git_sha(),
        provider_versions=(
            {"fixture": "1"}
            if args.source == "fixture"
            else {"akshare": importlib.metadata.version("akshare")}
        ),
    )
    print(f"manifest={manifest}")
    print(f"fetched_scopes={fetched}")
    print(f"reused_scopes={reused}")
    print(f"failed_scopes={failed}")
    return 2 if failed else 0


def _membership_symbols(path: Path) -> tuple[str, ...]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    symbols = {
        normalize_a_share_symbol(str(row.get("symbol", "")).strip())
        for row in rows
        if str(row.get("symbol", "")).strip()
    }
    if not symbols:
        raise ValueError("membership CSV must contain at least one symbol")
    return tuple(sorted(symbols))


def _fixture(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("fixture input must be a JSON object")
    return payload


def _fetch_rows(
    source: str,
    fixture: Mapping[str, object] | None,
    provider: AkShareProvider | None,
    symbol: str,
    start: date,
    end: date,
) -> list[dict[str, object]]:
    if source in {"akshare", "akshare-sina", "akshare-tencent"}:
        if provider is None:
            raise RuntimeError("AkShare provider is unavailable")
        return provider.history(symbol, start, end)
    if fixture is None or symbol not in fixture:
        raise ValueError(f"fixture is missing {symbol}")
    value = fixture[symbol]
    if isinstance(value, dict) and "error" in value:
        raise RuntimeError(str(value["error"]))
    if not isinstance(value, list):
        raise ValueError(f"fixture {symbol} must be a list")
    return [normalize_daily_bar(symbol, dict(row), "fixture") for row in value]


def _parent_manifest(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("layer") != "raw":
        raise ValueError("resume manifest must describe a raw run")
    return payload


def _verified_parent_scope(
    parent: Mapping[str, object] | None,
    parent_path: Path | None,
    symbol: str,
) -> Mapping[str, object] | None:
    if parent is None or parent_path is None:
        return None
    for scope in parent.get("scopes", []):
        if not isinstance(scope, dict) or scope.get("symbol") != symbol:
            continue
        if scope.get("status") not in {"success", "empty", "reused"} or not scope.get("artifact"):
            return None
        relative = str(scope["artifact"])
        artifact = next(
            (
                item
                for item in parent.get("artifacts", [])
                if isinstance(item, dict) and item.get("path") == relative
            ),
            None,
        )
        path = parent_path.parent / relative
        if artifact is None or sha256_file(path) != artifact.get("sha256"):
            raise ValueError(f"resume artifact hash mismatch: {relative}")
        return scope
    return None


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
