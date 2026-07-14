from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.data.historical_universe import (  # noqa: E402
    active_symbols,
    load_membership_intervals,
)
from fintech_quant.data.manifest_chain import (  # noqa: E402
    load_verified_manifest,
    load_verified_manifest_chain,
)
from fintech_quant.data.run_artifacts import sha256_file  # noqa: E402
from fintech_quant.data.symbols import normalize_a_share_symbol  # noqa: E402


Runner = Callable[..., None]


@dataclass(frozen=True)
class PipelineConfig:
    as_of: date
    state: Path
    account: Path
    membership: Path
    comparison: Path
    raw_price_root: Path
    processed_price_root: Path
    raw_factor_root: Path
    processed_factor_root: Path
    raw_action_root: Path
    processed_action_root: Path
    cycle_root: Path
    benchmark_start: date
    constituent_timeout: int = 60
    stage_timeout: int = 1800
    paper_timeout: int = 600


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one deterministic, baseline-only CSI 300 post-close paper cycle."
    )
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--membership", required=True)
    parser.add_argument("--comparison", required=True)
    parser.add_argument("--raw-price-root", default="data/diagnostics/raw-price-runs")
    parser.add_argument(
        "--processed-price-root", default="data/diagnostics/processed-price-runs"
    )
    parser.add_argument("--raw-factor-root", default="data/diagnostics/raw-factor-runs")
    parser.add_argument(
        "--processed-factor-root", default="data/diagnostics/processed-factor-runs"
    )
    parser.add_argument(
        "--raw-action-root", default="data/diagnostics/raw-corporate-action-runs"
    )
    parser.add_argument(
        "--processed-action-root",
        default="data/diagnostics/processed-corporate-action-runs",
    )
    parser.add_argument(
        "--cycle-root", default="outputs/paper_trading/csi300_baseline/cycles"
    )
    parser.add_argument("--benchmark-start", default="2020-06-01")
    parser.add_argument("--constituent-timeout", type=int, default=60)
    parser.add_argument("--stage-timeout", type=int, default=1800)
    parser.add_argument("--paper-timeout", type=int, default=600)
    args = parser.parse_args()
    config = PipelineConfig(
        as_of=date.fromisoformat(args.as_of),
        state=Path(args.state),
        account=Path(args.account),
        membership=Path(args.membership),
        comparison=Path(args.comparison),
        raw_price_root=Path(args.raw_price_root),
        processed_price_root=Path(args.processed_price_root),
        raw_factor_root=Path(args.raw_factor_root),
        processed_factor_root=Path(args.processed_factor_root),
        raw_action_root=Path(args.raw_action_root),
        processed_action_root=Path(args.processed_action_root),
        cycle_root=Path(args.cycle_root),
        benchmark_start=date.fromisoformat(args.benchmark_start),
        constituent_timeout=args.constituent_timeout,
        stage_timeout=args.stage_timeout,
        paper_timeout=args.paper_timeout,
    )
    result = run_pipeline(config)
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


def run_pipeline(config: PipelineConfig, *, runner: Runner | None = None) -> dict[str, object]:
    active_runner = runner or _run
    _require_positive_timeouts(config)
    state = _load_state(config.state)
    validation_anchor = _verified_reference(state, "validation_anchor")
    previous_as_of = date.fromisoformat(str(state["last_successful_as_of"]))
    if config.as_of < previous_as_of:
        raise ValueError("as_of must not precede pipeline state")
    if config.as_of == previous_as_of:
        _validate_completed_state(state, config)
        return {"status": "already_completed", "as_of": config.as_of.isoformat()}

    parent_manifests = _verified_state_manifests(state)
    evidence_parent = (
        _verified_reference(state, "cycle_manifest")
        if isinstance(state.get("cycle_manifest"), Mapping)
        else validation_anchor
    )
    start = previous_as_of + timedelta(days=1)
    date_token = config.as_of.strftime("%Y%m%d")
    cycle_dir = config.cycle_root / config.as_of.isoformat()
    current_universe = cycle_dir / "current_universe.csv"
    benchmark = cycle_dir / "csi300_market_state.csv"
    decision_report = cycle_dir / "decision_report.json"
    data_health = cycle_dir / "data_health.json"
    targets = cycle_dir / "targets.csv"
    paper_report = cycle_dir / "paper_report.json"
    dashboard = cycle_dir / "dashboard.html"
    cycle_manifest = cycle_dir / "cycle_manifest.json"

    active_runner(
        [
            "scripts/fetch_index_universe.py",
            "--index-code",
            "000300",
            "--output",
            str(current_universe),
        ],
        timeout=config.constituent_timeout,
    )
    _validate_current_constituents(current_universe, config.membership, config.as_of)

    signal_raw, signal_processed = _price_stage(
        config,
        runner=active_runner,
        label="signal-price",
        date_token=date_token,
        start=start,
        parent=parent_manifests["signal_price"]["raw_manifest"],
        adjust="hfq",
        source="akshare-sina",
        workers=1,
    )
    execution_raw, execution_processed = _price_stage(
        config,
        runner=active_runner,
        label="execution-price",
        date_token=date_token,
        start=start,
        parent=parent_manifests["execution_price"]["raw_manifest"],
        adjust="none",
        source="akshare-tencent",
        workers=8,
    )

    active_runner(
        [
            "scripts/fetch_market_state.py",
            "--index-symbol",
            "sh000300",
            "--start",
            config.benchmark_start.isoformat(),
            "--end",
            config.as_of.isoformat(),
            "--output",
            str(benchmark),
        ],
        timeout=config.stage_timeout,
    )
    _require_file(benchmark, "benchmark")

    factor_raw, factor_processed = _factor_stage(
        config,
        runner=active_runner,
        date_token=date_token,
        start=start,
        parent=parent_manifests["factor"]["raw_manifest"],
        benchmark=benchmark,
        signal_features=signal_processed.parent / "features.csv",
    )
    action_raw, action_processed = _action_stage(
        config,
        runner=active_runner,
        date_token=date_token,
        start=start,
        parent=parent_manifests["corporate_action"]["raw_manifest"],
    )

    active_runner(
        [
            "scripts/build_daily_decision_report.py",
            "--factor-manifest",
            str(factor_processed),
            "--signal-price-manifest",
            str(signal_processed),
            "--execution-price-manifest",
            str(execution_processed),
            "--corporate-action-manifest",
            str(action_processed),
            "--benchmark",
            str(benchmark),
            "--membership",
            str(config.membership),
            "--as-of",
            config.as_of.isoformat(),
            "--output",
            str(decision_report),
            "--data-health-output",
            str(data_health),
        ],
        timeout=config.stage_timeout,
    )
    _require_file(decision_report, "daily decision report")
    if _load_json(data_health).get("passed") is not True:
        raise ValueError("daily data health did not pass")

    active_runner(
        [
            "scripts/run_post_close_daily_cycle.py",
            "--as-of",
            config.as_of.isoformat(),
            "--research-report",
            str(decision_report),
            "--features",
            str(execution_processed.parent / "daily.csv"),
            "--comparison",
            str(config.comparison),
            "--current-universe",
            str(current_universe),
            "--benchmark",
            str(benchmark),
            "--evidence-parent",
            str(evidence_parent),
            "--corporate-actions",
            str(action_processed.parent / "corporate_actions.csv"),
            "--data-health",
            str(data_health),
            "--account",
            str(config.account),
            "--targets-output",
            str(targets),
            "--paper-report",
            str(paper_report),
            "--dashboard-output",
            str(dashboard),
            "--cycle-manifest",
            str(cycle_manifest),
            "--slippage-rate",
            "0.0005",
        ],
        timeout=config.paper_timeout,
    )
    _require_processed_account(config.account, config.as_of)
    if _load_json(cycle_manifest).get("as_of") != config.as_of.isoformat():
        raise ValueError("paper cycle manifest as_of mismatch")

    new_state = {
        "schema_version": 1,
        "last_successful_as_of": config.as_of.isoformat(),
        "git_sha": _git_sha(),
        "validation_anchor": dict(state["validation_anchor"]),
        "membership": _reference(config.membership),
        "comparison": _reference(config.comparison),
        "current_universe": _reference(current_universe),
        "benchmark": _reference(benchmark),
        "decision_report": _reference(decision_report),
        "data_health": _reference(data_health),
        "cycle_manifest": _reference(cycle_manifest),
        "account": _reference(config.account),
        "manifests": {
            "signal_price": _manifest_state(signal_raw, signal_processed),
            "execution_price": _manifest_state(execution_raw, execution_processed),
            "factor": _manifest_state(factor_raw, factor_processed),
            "corporate_action": _manifest_state(action_raw, action_processed),
        },
    }
    _write_state_atomic(config.state, new_state)
    return {
        "status": "completed",
        "as_of": config.as_of.isoformat(),
        "state": str(config.state),
        "cycle_manifest": str(cycle_manifest),
    }


def _price_stage(
    config: PipelineConfig,
    *,
    runner: Runner,
    label: str,
    date_token: str,
    start: date,
    parent: Path,
    adjust: str,
    source: str,
    workers: int,
) -> tuple[Path, Path]:
    raw_run_id = f"csi300-{label}-raw-{date_token}"
    processed_run_id = f"csi300-{label}-{date_token}"
    raw_manifest = config.raw_price_root / raw_run_id / "manifest.json"
    processed_manifest = config.processed_price_root / processed_run_id / "manifest.json"
    runner(
        [
            "scripts/collect_historical_prices.py",
            "--source",
            source,
            "--membership",
            str(config.membership),
            "--start",
            start.isoformat(),
            "--end",
            config.as_of.isoformat(),
            "--run-id",
            raw_run_id,
            "--raw-root",
            str(config.raw_price_root),
            "--append-from",
            str(parent),
            "--adjust",
            adjust,
            "--workers",
            str(workers),
        ],
        timeout=config.stage_timeout,
    )
    load_verified_manifest_chain(raw_manifest, expected_layer="raw")
    runner(
        [
            "scripts/build_historical_price_features.py",
            "--raw-manifest",
            str(raw_manifest),
            "--run-id",
            processed_run_id,
            "--processed-root",
            str(config.processed_price_root),
        ],
        timeout=config.stage_timeout,
    )
    load_verified_manifest(processed_manifest, expected_layer="processed")
    return raw_manifest.resolve(), processed_manifest.resolve()


def _factor_stage(
    config: PipelineConfig,
    *,
    runner: Runner,
    date_token: str,
    start: date,
    parent: Path,
    benchmark: Path,
    signal_features: Path,
) -> tuple[Path, Path]:
    raw_run_id = f"csi300-factor-raw-{date_token}"
    processed_run_id = f"csi300-factor-{date_token}"
    raw_manifest = config.raw_factor_root / raw_run_id / "manifest.json"
    processed_manifest = config.processed_factor_root / processed_run_id / "manifest.json"
    runner(
        [
            "scripts/collect_point_in_time_factors.py",
            "--source",
            "akshare",
            "--membership",
            str(config.membership),
            "--start",
            start.isoformat(),
            "--end",
            config.as_of.isoformat(),
            "--run-id",
            raw_run_id,
            "--raw-root",
            str(config.raw_factor_root),
            "--append-from",
            str(parent),
            "--groups",
            "fundamentals",
            "financial_statements",
            "--workers",
            "4",
        ],
        timeout=config.stage_timeout,
    )
    load_verified_manifest_chain(raw_manifest, expected_layer="raw")
    runner(
        [
            "scripts/build_point_in_time_factors.py",
            "--raw-manifest",
            str(raw_manifest),
            "--trading-calendar",
            str(benchmark),
            "--run-id",
            processed_run_id,
            "--processed-root",
            str(config.processed_factor_root),
            "--capital-flow-mode",
            "price-volume-proxy",
            "--price-features",
            str(signal_features),
        ],
        timeout=config.stage_timeout,
    )
    load_verified_manifest(processed_manifest, expected_layer="processed")
    return raw_manifest.resolve(), processed_manifest.resolve()


def _action_stage(
    config: PipelineConfig,
    *,
    runner: Runner,
    date_token: str,
    start: date,
    parent: Path,
) -> tuple[Path, Path]:
    raw_run_id = f"csi300-action-raw-{date_token}"
    processed_run_id = f"csi300-action-{date_token}"
    raw_manifest = config.raw_action_root / raw_run_id / "manifest.json"
    processed_manifest = config.processed_action_root / processed_run_id / "manifest.json"
    runner(
        [
            "scripts/collect_corporate_actions.py",
            "--source",
            "akshare-sina",
            "--membership",
            str(config.membership),
            "--start",
            start.isoformat(),
            "--end",
            config.as_of.isoformat(),
            "--run-id",
            raw_run_id,
            "--raw-root",
            str(config.raw_action_root),
            "--append-from",
            str(parent),
            "--workers",
            "4",
        ],
        timeout=config.stage_timeout,
    )
    load_verified_manifest_chain(raw_manifest, expected_layer="raw")
    runner(
        [
            "scripts/build_corporate_actions.py",
            "--raw-manifest",
            str(raw_manifest),
            "--run-id",
            processed_run_id,
            "--processed-root",
            str(config.processed_action_root),
        ],
        timeout=config.stage_timeout,
    )
    load_verified_manifest(processed_manifest, expected_layer="processed")
    return raw_manifest.resolve(), processed_manifest.resolve()


def _verified_state_manifests(state: Mapping[str, object]) -> dict[str, dict[str, Path]]:
    manifests = state.get("manifests")
    if not isinstance(manifests, Mapping):
        raise ValueError("pipeline state manifests must be an object")
    result: dict[str, dict[str, Path]] = {}
    for name in ("signal_price", "execution_price", "factor", "corporate_action"):
        item = manifests.get(name)
        if not isinstance(item, Mapping):
            raise ValueError(f"pipeline state missing {name} manifests")
        raw = Path(str(item["raw_manifest"])).resolve()
        processed = Path(str(item["processed_manifest"])).resolve()
        if item.get("raw_manifest_sha256") != sha256_file(raw):
            raise ValueError(f"pipeline state {name} raw manifest hash mismatch")
        if item.get("processed_manifest_sha256") != sha256_file(processed):
            raise ValueError(f"pipeline state {name} processed manifest hash mismatch")
        load_verified_manifest_chain(raw, expected_layer="raw")
        load_verified_manifest(processed, expected_layer="processed")
        result[name] = {"raw_manifest": raw, "processed_manifest": processed}
    return result


def _verified_reference(state: Mapping[str, object], key: str) -> Path:
    value = state.get(key)
    label = key.replace("_", " ")
    if not isinstance(value, Mapping):
        raise ValueError(f"pipeline state is missing {label}")
    raw_path = value.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError(f"pipeline state {label} path is missing")
    path = Path(raw_path).resolve()
    if not path.is_file() or value.get("sha256") != sha256_file(path):
        raise ValueError(f"pipeline state {label} hash mismatch")
    if value.get("bytes") != path.stat().st_size:
        raise ValueError(f"pipeline state {label} byte count mismatch")
    return path


def _validate_current_constituents(current: Path, membership: Path, as_of: date) -> None:
    with current.open(encoding="utf-8", newline="") as handle:
        symbols = tuple(
            sorted(
                {
                    normalize_a_share_symbol(str(row.get("symbol", "")))
                    for row in csv.DictReader(handle)
                    if str(row.get("symbol", "")).strip()
                }
            )
        )
    expected = active_symbols(load_membership_intervals(membership), as_of)
    if len(symbols) != 300 or len(expected) != 300:
        raise ValueError(
            f"CSI 300 constituent count mismatch: fetched={len(symbols)} historical={len(expected)}"
        )
    if symbols != expected:
        missing = sorted(set(expected) - set(symbols))
        extra = sorted(set(symbols) - set(expected))
        raise ValueError(
            "current constituents differ from historical membership: "
            f"missing={missing[:3]} extra={extra[:3]}"
        )


def _load_state(path: Path) -> dict[str, object]:
    payload = _load_json(path)
    if payload.get("schema_version") != 1 or not payload.get("last_successful_as_of"):
        raise ValueError("unsupported or incomplete pipeline state")
    return payload


def _validate_completed_state(state: Mapping[str, object], config: PipelineConfig) -> None:
    account = _load_json(config.account)
    if account.get("last_processed_date") != config.as_of.isoformat():
        raise ValueError("pipeline state date does not match paper account")
    reference = state.get("cycle_manifest")
    if not isinstance(reference, Mapping):
        raise ValueError("pipeline state is missing cycle manifest evidence")
    path = Path(str(reference["path"]))
    if not path.exists() or reference.get("sha256") != sha256_file(path):
        raise ValueError("pipeline state cycle manifest hash mismatch")


def _require_positive_timeouts(config: PipelineConfig) -> None:
    if min(config.constituent_timeout, config.stage_timeout, config.paper_timeout) <= 0:
        raise ValueError("pipeline timeouts must be positive")


def _require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise ValueError(f"{label} was not produced: {path}")


def _require_processed_account(path: Path, as_of: date) -> None:
    if _load_json(path).get("last_processed_date") != as_of.isoformat():
        raise ValueError("paper account did not commit the requested date")


def _manifest_state(raw: Path, processed: Path) -> dict[str, str]:
    return {
        "raw_manifest": str(raw.resolve()),
        "raw_manifest_sha256": sha256_file(raw),
        "processed_manifest": str(processed.resolve()),
        "processed_manifest_sha256": sha256_file(processed),
    }


def _reference(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _write_state_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        staged.write_text(
            json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _fsync_file(staged)
        os.replace(staged, path)
        _fsync_directory(path.parent)
    finally:
        staged.unlink(missing_ok=True)


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _run(command: list[str], *, timeout: int) -> None:
    subprocess.run(
        [sys.executable, *command],
        cwd=ROOT,
        check=True,
        timeout=timeout,
    )


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
