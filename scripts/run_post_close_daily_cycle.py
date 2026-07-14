from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path
from typing import BinaryIO, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fintech_quant.execution.paper_evidence import (  # noqa: E402
    approved_paper_policy,
    canonical_json_sha256,
    file_reference,
    verify_file_reference,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the post-close paper-trading and monitoring cycle."
    )
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--research-report", required=True)
    parser.add_argument("--features", required=True)
    parser.add_argument("--comparison", required=True)
    parser.add_argument("--current-universe", default=None)
    parser.add_argument("--benchmark", default=None)
    parser.add_argument("--evidence-parent", default=None)
    parser.add_argument("--dqn-report", default=None)
    parser.add_argument("--corporate-actions", default=None)
    parser.add_argument("--walk-forward", default=None)
    parser.add_argument("--data-health", default=None)
    parser.add_argument("--information-health", default=None)
    parser.add_argument("--account", default="data/paper/account.json")
    parser.add_argument("--targets-output", default=None)
    parser.add_argument("--paper-report", default=None)
    parser.add_argument("--dashboard-output", default="outputs/research_dashboard.html")
    parser.add_argument("--cycle-manifest", default=None)
    parser.add_argument("--buy-threshold", type=float, default=70.0)
    parser.add_argument("--min-score-confidence", type=float, default=0.8)
    parser.add_argument("--max-position-weight", type=float, default=0.08)
    parser.add_argument("--max-targets", type=int, default=None)
    parser.add_argument("--dqn-default-action", choices=("buy", "hold", "sell"), default="hold")
    parser.add_argument("--dqn-flat-action", choices=("buy", "hold", "sell"), default="hold")
    parser.add_argument("--initial-cash", type=float, default=100000.0)
    parser.add_argument("--commission-rate", type=float, default=0.0003)
    parser.add_argument("--minimum-commission", type=float, default=5.0)
    parser.add_argument("--slippage-rate", type=float, default=0.0005)
    args = parser.parse_args()

    v2_options = (args.current_universe, args.benchmark, args.evidence_parent)
    if any(v2_options) and not all(v2_options):
        raise ValueError(
            "V2 cycles require --current-universe, --benchmark, and --evidence-parent"
        )
    v2_enabled = all(v2_options)
    if v2_enabled:
        _validate_v2_policy(args)

    as_of = date.fromisoformat(args.as_of)
    account = Path(args.account)
    targets = Path(args.targets_output or f"outputs/paper_trading/targets_{args.as_of}.csv")
    paper_report = Path(
        args.paper_report or f"outputs/paper_trading/report_{args.as_of}.json"
    )
    dashboard = Path(args.dashboard_output)
    cycle_manifest = Path(
        args.cycle_manifest or f"outputs/paper_trading/cycle_{args.as_of}.json"
    )
    canonical_paths = (account, targets, paper_report, dashboard, cycle_manifest)
    if len({path.resolve() for path in canonical_paths}) != len(canonical_paths):
        raise ValueError("post-close output paths must be distinct")

    lock = _acquire_lock(account)
    staged_paths: list[Path] = []
    try:
        last_processed = _last_processed_date(account)
        if last_processed is not None and last_processed > as_of:
            raise ValueError("paper as_of must not precede last processed date")
        if last_processed == as_of:
            _validate_completed_cycle(
                cycle_manifest,
                as_of=args.as_of,
                account=account,
            )
            print("already_completed=true")
            print(f"cycle_manifest_path={cycle_manifest}")
            return 0

        staged_account = _staged_path(account)
        staged_targets = _staged_path(targets)
        staged_report = _staged_path(paper_report)
        staged_dashboard = _staged_path(dashboard)
        staged_manifest = _staged_path(cycle_manifest)
        staged_paths.extend(
            [
                staged_account,
                staged_targets,
                staged_report,
                staged_dashboard,
                staged_manifest,
            ]
        )
        if account.exists():
            shutil.copy2(account, staged_account)
        account_before_sha256 = _sha256(account) if account.exists() else None

        paper_command = [
            "scripts/run_daily_paper_trading.py",
            "--research-report",
            args.research_report,
            "--features",
            args.features,
            "--as-of",
            args.as_of,
            "--account",
            str(staged_account),
            "--targets-output",
            str(staged_targets),
            "--paper-report",
            str(staged_report),
            "--buy-threshold",
            str(args.buy_threshold),
            "--min-score-confidence",
            str(args.min_score_confidence),
            "--max-position-weight",
            str(args.max_position_weight),
            "--initial-cash",
            str(args.initial_cash),
            "--commission-rate",
            str(args.commission_rate),
            "--minimum-commission",
            str(args.minimum_commission),
            "--slippage-rate",
            str(args.slippage_rate),
        ]
        if args.max_targets is not None:
            paper_command.extend(["--max-targets", str(args.max_targets)])
        if args.corporate_actions:
            paper_command.extend(["--corporate-actions", args.corporate_actions])
        if args.dqn_report:
            paper_command.extend(
                [
                    "--dqn-report",
                    args.dqn_report,
                    "--dqn-default-action",
                    args.dqn_default_action,
                    "--dqn-flat-action",
                    args.dqn_flat_action,
                ]
            )
        _run(paper_command)

        dashboard_command = [
            "scripts/build_research_dashboard.py",
            "--comparison",
            args.comparison,
            "--paper-report",
            str(staged_report),
            "--run-report",
            args.research_report,
            "--output",
            str(staged_dashboard),
        ]
        if args.walk_forward:
            dashboard_command.extend(["--walk-forward", args.walk_forward])
        if args.data_health:
            dashboard_command.extend(["--data-health", args.data_health])
        if args.information_health:
            dashboard_command.extend(["--information-health", args.information_health])
        _run(dashboard_command)

        _load_json(staged_account)
        report_payload = _load_json(staged_report)
        account_payload = report_payload.get("account")
        if not isinstance(account_payload, Mapping):
            raise ValueError("paper report account must be an object")
        account_after_sha256 = _sha256(staged_account)
        if canonical_json_sha256(account_payload) != account_after_sha256:
            raise ValueError("paper report account does not match staged paper account")
        manifest_payload = _manifest_payload(
            args=args,
            account_before_sha256=account_before_sha256,
            account_after_sha256=account_after_sha256,
            targets=targets,
            staged_targets=staged_targets,
            paper_report=paper_report,
            staged_report=staged_report,
            dashboard=dashboard,
            staged_dashboard=staged_dashboard,
            v2_enabled=v2_enabled,
        )
        _write_json(staged_manifest, manifest_payload)
        _load_json(staged_manifest)

        for staged in (
            staged_targets,
            staged_report,
            staged_dashboard,
            staged_manifest,
            staged_account,
        ):
            _fsync_file(staged)
        for staged, canonical in (
            (staged_targets, targets),
            (staged_report, paper_report),
            (staged_dashboard, dashboard),
            (staged_manifest, cycle_manifest),
            (staged_account, account),
        ):
            canonical.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, canonical)
        for parent in {path.parent for path in canonical_paths}:
            _fsync_directory(parent)

        print(f"targets_path={targets}")
        print(f"paper_report_path={paper_report}")
        print(f"dashboard_path={dashboard}")
        print(f"cycle_manifest_path={cycle_manifest}")
        return 0
    finally:
        for path in staged_paths:
            path.unlink(missing_ok=True)
        _release_lock(lock)


def _run(command: list[str]) -> None:
    subprocess.run([sys.executable, *command], cwd=ROOT, check=True)


def _staged_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")


def _acquire_lock(account: Path) -> BinaryIO:
    lock_path = account.with_name(f"{account.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError("another post-close cycle holds the paper account lock") from None
    return handle


def _release_lock(handle: BinaryIO) -> None:
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    handle.close()


def _last_processed_date(account: Path) -> date | None:
    if not account.exists():
        return None
    value = _load_json(account).get("last_processed_date")
    return date.fromisoformat(str(value)) if value else None


def _validate_completed_cycle(manifest: Path, *, as_of: str, account: Path) -> None:
    if not manifest.exists():
        raise ValueError("processed paper date is missing its cycle manifest")
    payload = _load_json(manifest)
    if payload.get("as_of") != as_of:
        raise ValueError("cycle manifest as_of does not match processed paper date")
    if payload.get("account_after_sha256") != _sha256(account):
        raise ValueError("cycle manifest account hash mismatch")
    if payload.get("schema_version") == 2:
        if payload.get("kind") != "paper_trading_cycle":
            raise ValueError("V2 cycle manifest kind is invalid")
        if payload.get("policy") != approved_paper_policy():
            raise ValueError("V2 cycle manifest policy mismatch")
        parent = payload.get("evidence_parent")
        if not isinstance(parent, Mapping):
            raise ValueError("V2 cycle manifest evidence parent is missing")
        verify_file_reference(parent)
        inputs = payload.get("inputs")
        if not isinstance(inputs, Mapping):
            raise ValueError("V2 cycle manifest inputs must be an object")
        for name in (
            "research_report",
            "execution_prices",
            "comparison",
            "current_universe",
            "benchmark",
        ):
            reference = inputs.get(name)
            if not isinstance(reference, Mapping):
                raise ValueError(f"V2 cycle manifest missing {name} input")
            verify_file_reference(reference)
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("cycle manifest artifacts must be an object")
    for name in ("targets", "paper_report", "dashboard"):
        item = artifacts.get(name)
        if not isinstance(item, dict):
            raise ValueError(f"cycle manifest missing {name} artifact")
        path = Path(str(item["path"]))
        if not path.exists() or item.get("sha256") != _sha256(path):
            raise ValueError(f"cycle manifest {name} artifact hash mismatch")


def _artifact(canonical: Path, staged: Path) -> dict[str, object]:
    return {
        "path": str(canonical.resolve()),
        "bytes": staged.stat().st_size,
        "sha256": _sha256(staged),
    }


def _validate_v2_policy(args: argparse.Namespace) -> None:
    if args.dqn_report:
        raise ValueError("V2 paper evidence forbids DQN exposure")
    if args.max_targets is not None:
        raise ValueError("V2 paper evidence forbids an unapproved max-targets override")
    expected = approved_paper_policy()
    actual = {
        "buy_threshold": args.buy_threshold,
        "minimum_score_confidence": args.min_score_confidence,
        "maximum_position_weight": args.max_position_weight,
        "commission_rate": args.commission_rate,
        "minimum_commission": args.minimum_commission,
        "slippage_rate": args.slippage_rate,
    }
    for name, value in actual.items():
        if value != expected[name]:
            raise ValueError(
                f"V2 paper evidence policy mismatch for {name}: "
                f"expected {expected[name]!r}, got {value!r}"
            )


def _manifest_payload(
    *,
    args: argparse.Namespace,
    account_before_sha256: str | None,
    account_after_sha256: str,
    targets: Path,
    staged_targets: Path,
    paper_report: Path,
    staged_report: Path,
    dashboard: Path,
    staged_dashboard: Path,
    v2_enabled: bool,
) -> dict[str, object]:
    artifacts = {
        "targets": _artifact(targets, staged_targets),
        "paper_report": _artifact(paper_report, staged_report),
        "dashboard": _artifact(dashboard, staged_dashboard),
    }
    common = {
        "as_of": args.as_of,
        "git_sha": _git_sha(),
        "account_before_sha256": account_before_sha256,
        "account_after_sha256": account_after_sha256,
        "artifacts": artifacts,
    }
    if not v2_enabled:
        return {"schema_version": 1, **common}

    input_paths = {
        "research_report": args.research_report,
        "execution_prices": args.features,
        "comparison": args.comparison,
        "current_universe": args.current_universe,
        "benchmark": args.benchmark,
        "corporate_actions": args.corporate_actions,
        "walk_forward": args.walk_forward,
        "data_health": args.data_health,
        "information_health": args.information_health,
    }
    return {
        "schema_version": 2,
        "kind": "paper_trading_cycle",
        **common,
        "evidence_parent": file_reference(Path(args.evidence_parent)),
        "inputs": {
            name: file_reference(Path(path))
            for name, path in input_paths.items()
            if path is not None
        },
        "policy": approved_paper_policy(),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _git_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
