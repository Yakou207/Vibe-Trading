from __future__ import annotations

import argparse
import importlib.metadata
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.data.historical_universe import membership_symbols_for_range  # noqa: E402
from fintech_quant.data.manifest_chain import load_verified_manifest_chain  # noqa: E402
from fintech_quant.data.run_artifacts import RunArtifactStore, sha256_file  # noqa: E402
from fintech_quant.information import (  # noqa: E402
    AkShareFinancialStatementFetcher,
    AkShareFundFlowFetcher,
    AkShareFundamentalFetcher,
    InformationRecord,
)


GROUPS = ("fundamentals", "financial_statements", "capital_flow")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect point-in-time factor inputs into an immutable raw run."
    )
    parser.add_argument("--source", choices=("akshare", "fixture"), default="akshare")
    parser.add_argument("--fixture-input", default=None)
    parser.add_argument("--membership", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--raw-root", default="data/raw/runs")
    parser.add_argument("--resume-from", default=None)
    parser.add_argument("--append-from", default=None)
    parser.add_argument("--created-at", default=None)
    parser.add_argument("--groups", nargs="+", choices=GROUPS, default=list(GROUPS))
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    if args.source == "fixture" and not args.fixture_input:
        raise SystemExit("--fixture-input is required when --source fixture")
    if args.resume_from and args.append_from:
        raise SystemExit("--resume-from and --append-from cannot be used together")
    if args.workers < 1:
        raise SystemExit("--workers must be positive")

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if end < start:
        raise SystemExit("--end must not be earlier than --start")
    symbols = _membership_symbols(Path(args.membership), start, end)
    parent_path = Path(args.resume_from).resolve() if args.resume_from else None
    parent = _load_parent_manifest(parent_path)
    append_path = Path(args.append_from).resolve() if args.append_from else None
    if append_path is not None:
        load_verified_manifest_chain(append_path, expected_layer="raw")
    fixture = _load_fixture(Path(args.fixture_input)) if args.fixture_input else None
    created_at = args.created_at or datetime.now(timezone.utc).isoformat()
    store = RunArtifactStore(
        Path(args.raw_root),
        args.run_id,
        layer="raw",
        parent_manifest=str(parent_path or append_path) if parent_path or append_path else None,
    )

    scopes: list[dict[str, object]] = []
    fetched_scopes = 0
    reused_scopes = 0
    failed_scopes = 0
    pending: list[tuple[str, str]] = []
    for symbol in symbols:
        for group in args.groups:
            relative_path = f"{group}/{symbol}.jsonl"
            parent_scope = _reusable_parent_scope(parent, parent_path, symbol, group)
            if parent_scope is not None and parent_path is not None:
                source = parent_path.parent / str(parent_scope["artifact"])
                store.copy_artifact(source, relative_path)
                scopes.append(
                    {
                        "symbol": symbol,
                        "group": group,
                        "status": "reused",
                        "artifact": relative_path,
                        "error": None,
                    }
                )
                reused_scopes += 1
                continue
            pending.append((symbol, group))

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_by_scope = {
            executor.submit(_fetch_rows, args.source, fixture, symbol, group, start, end): (
                symbol,
                group,
            )
            for symbol, group in pending
        }
        for completed, future in enumerate(as_completed(future_by_scope), start=1):
            symbol, group = future_by_scope[future]
            relative_path = f"{group}/{symbol}.jsonl"
            try:
                rows = future.result()
            except Exception as exc:
                scopes.append(
                    {
                        "symbol": symbol,
                        "group": group,
                        "status": "failed",
                        "artifact": None,
                        "error": str(exc),
                    }
                )
                failed_scopes += 1
            else:
                store.write_jsonl(relative_path, rows)
                scopes.append(
                    {
                        "symbol": symbol,
                        "group": group,
                        "status": "success" if rows else "empty",
                        "artifact": relative_path,
                        "error": None,
                    }
                )
                fetched_scopes += 1
            if completed % 25 == 0 or completed == len(pending):
                print(
                    f"progress={completed}/{len(pending)} failed={failed_scopes}",
                    flush=True,
                )

    scopes = sorted(scopes, key=lambda scope: (str(scope["symbol"]), str(scope["group"])))
    _write_collection_state(store.run_dir, scopes)
    membership_path = Path(args.membership).resolve()
    manifest_path = store.write_manifest(
        request={
            "source": args.source,
            "membership": str(membership_path),
            "membership_sha256": sha256_file(membership_path),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "symbols": list(symbols),
            "groups": list(args.groups),
        },
        scopes=scopes,
        created_at=created_at,
        git_sha=_git_sha(),
        provider_versions=_provider_versions(args.source),
    )
    print(f"manifest={manifest_path}")
    print(f"fetched_scopes={fetched_scopes}")
    print(f"reused_scopes={reused_scopes}")
    print(f"failed_scopes={failed_scopes}")
    return 2 if failed_scopes else 0


def _membership_symbols(path: Path, start: date, end: date) -> tuple[str, ...]:
    return membership_symbols_for_range(path, start, end)


def _load_fixture(path: Path) -> dict[str, dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("fixture input must be a JSON object")
    return {str(symbol): dict(groups) for symbol, groups in payload.items()}


def _fetch_rows(
    source: str,
    fixture: Mapping[str, Mapping[str, object]] | None,
    symbol: str,
    group: str,
    start: date,
    end: date,
) -> list[dict[str, object]]:
    if source == "fixture":
        if fixture is None or symbol not in fixture or group not in fixture[symbol]:
            raise ValueError(f"fixture is missing {symbol} {group}")
        value = fixture[symbol][group]
        if isinstance(value, dict) and "error" in value:
            raise RuntimeError(str(value["error"]))
        if not isinstance(value, list):
            raise ValueError(f"fixture {symbol} {group} must be a list")
        return [dict(row) for row in value]

    fetcher_factory: dict[str, Callable[[], object]] = {
        "fundamentals": lambda: AkShareFundamentalFetcher(as_of=end),
        "financial_statements": AkShareFinancialStatementFetcher,
        "capital_flow": AkShareFundFlowFetcher,
    }
    fetcher = fetcher_factory[group]()
    records = fetcher.fetch(symbol, None, start, end)  # type: ignore[attr-defined]
    return [_record_to_json(record) for record in records]


def _record_to_json(record: InformationRecord) -> dict[str, object]:
    payload = asdict(record)
    payload["symbol"] = record.normalized_symbol
    payload["published_at"] = record.published_at.isoformat()
    payload["category"] = record.category.value
    payload["risk_tags"] = list(record.risk_tags)
    return payload


def _load_parent_manifest(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("layer") != "raw":
        raise ValueError("resume manifest must describe a raw run")
    return payload


def _reusable_parent_scope(
    parent: Mapping[str, object] | None,
    parent_path: Path | None,
    symbol: str,
    group: str,
) -> Mapping[str, object] | None:
    if parent is None or parent_path is None:
        return None
    scopes = parent.get("scopes", [])
    if not isinstance(scopes, list):
        raise ValueError("resume manifest scopes must be a list")
    for item in scopes:
        if not isinstance(item, dict):
            continue
        if item.get("symbol") == symbol and item.get("group") == group:
            if item.get("status") in {"success", "empty", "reused"} and item.get("artifact"):
                relative = str(item["artifact"])
                artifact = next(
                    (
                        candidate
                        for candidate in parent.get("artifacts", [])
                        if isinstance(candidate, dict) and candidate.get("path") == relative
                    ),
                    None,
                )
                path = (parent_path.parent / relative).resolve()
                if artifact is None or sha256_file(path) != artifact.get("sha256"):
                    raise ValueError(f"resume artifact hash mismatch: {relative}")
                return item
            return None
    return None


def _git_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _provider_versions(source: str) -> dict[str, str]:
    if source == "fixture":
        return {"fixture": "1"}
    return {"akshare": importlib.metadata.version("akshare")}


def _write_collection_state(run_dir: Path, scopes: Sequence[Mapping[str, object]]) -> None:
    completed = sum(1 for scope in scopes if scope.get("status") in {"success", "empty", "reused"})
    failed = sum(1 for scope in scopes if scope.get("status") == "failed")
    (run_dir / "collection_state.json").write_text(
        json.dumps(
            {
                "completed_scopes": completed,
                "failed_scopes": failed,
                "scopes": [dict(scope) for scope in scopes],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
