"""Bridge an all-cash CSI 300 paper account across an operational gap into a new epoch.

The daily entrypoint only advances one trading session per run. When sessions were
missed and the canonical account holds no positions, replaying every missed session
adds no economic information: an all-cash account has no PnL to mark. This script
instead collects one immutable data increment for the whole gap, cancels the stale
queued targets, and creates a non-counted schema-2 validation anchor that supersedes
the previous epoch. Nothing produced here counts toward paper evidence.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (SRC, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fintech_quant.data.run_artifacts import sha256_file  # noqa: E402
from fintech_quant.execution.paper_evidence import (  # noqa: E402
    approved_paper_policy,
    create_validation_anchor,
    file_reference,
    load_verified_anchor,
    verify_file_reference,
)
from scripts.initialize_csi300_paper_validation import (  # noqa: E402
    _optional_verified_latest_report_reference,
    _verified_latest_cycle_reference,
)
from scripts.run_csi300_post_close import (  # noqa: E402
    PipelineConfig,
    Runner,
    _action_stage,
    _active_evidence_parent,
    _copy_file_atomic,
    _factor_stage,
    _git_sha,
    _load_json,
    _load_state,
    _manifest_state,
    _price_stage,
    _reference,
    _require_account_state_alignment,
    _require_file,
    _require_positive_timeouts,
    _run,
    _validate_current_constituents,
    _verified_reference,
    _verified_state_manifests,
    _write_state_atomic,
)


EMPTY_ACCOUNT_BOOKS = (
    "positions",
    "shadow_positions",
    "dividend_tax_lots",
    "shadow_dividend_tax_lots",
)


def run_bridge(
    config: PipelineConfig,
    *,
    formal_run_manifest: Path,
    validation_root: Path,
    reason: str,
    created_at: str | None = None,
    runner: Runner | None = None,
) -> dict[str, object]:
    active_runner = runner or _run
    _require_positive_timeouts(config)
    if not reason.strip():
        raise ValueError("an epoch bridge requires a recorded reason")

    state = _load_state(config.state)
    validation_anchor = _verified_reference(state, "validation_anchor")
    load_verified_anchor(validation_anchor)
    previous_as_of = date.fromisoformat(str(state["last_successful_as_of"]))
    if config.as_of <= previous_as_of:
        raise ValueError("bridge end date must follow the pipeline state date")
    _require_account_state_alignment(config.account, previous_as_of)
    evidence_parent = _active_evidence_parent(
        state,
        validation_anchor=validation_anchor,
        account=config.account,
        state_date=previous_as_of,
    )
    account_payload = _load_json(config.account)
    _require_all_cash(account_payload)
    supersedes = _superseded_references(
        state,
        account=config.account,
        validation_anchor=validation_anchor,
        evidence_parent=evidence_parent,
    )
    parent_manifests = _verified_state_manifests(state)

    validation_root = validation_root.resolve()
    validation_root.mkdir(parents=True, exist_ok=True)
    bridge_dir = validation_root / (f"bridge-{previous_as_of:%Y%m%d}-{config.as_of:%Y%m%d}")
    bridge_dir.mkdir(exist_ok=False)
    anchor_manifest: Path | None = None
    account_published = False
    try:
        data = _collect_bridge_data(
            config,
            runner=active_runner,
            bridge_dir=bridge_dir,
            start=previous_as_of + timedelta(days=1),
            parent_manifests=parent_manifests,
        )
        timestamp = created_at or datetime.now(timezone.utc).isoformat()
        git_sha = _git_sha()

        account_before = bridge_dir / "account_before.json"
        state_before = bridge_dir / "pipeline_state_before.json"
        shutil.copyfile(config.account, account_before)
        shutil.copyfile(config.state, state_before)
        cancelled = {
            "signal_date": account_payload.get("pending_signal_date"),
            "targets": dict(account_payload.get("pending_targets") or {}),
        }
        account_after = bridge_dir / "account_after.json"
        _write_json(
            account_after,
            {
                **account_payload,
                "last_processed_date": config.as_of.isoformat(),
                "pending_signal_date": None,
                "pending_targets": {},
            },
        )

        bridge_manifest = bridge_dir / "bridge_manifest.json"
        _write_json(
            bridge_manifest,
            {
                "schema_version": 1,
                "kind": "paper_epoch_bridge",
                "counts_toward_evidence": False,
                "from_as_of": previous_as_of.isoformat(),
                "to_as_of": config.as_of.isoformat(),
                "created_at": timestamp,
                "git_sha": git_sha,
                "reason": reason,
                "policy": approved_paper_policy(),
                "account_requirements": {name: "empty" for name in EMPTY_ACCOUNT_BOOKS},
                "cancelled_targets": cancelled,
                "superseded": supersedes,
                "artifacts": {
                    "account_before": file_reference(account_before),
                    "account_after": file_reference(account_after),
                    "pipeline_state_before": file_reference(state_before),
                    "current_universe": file_reference(data["current_universe"]),
                    "benchmark": file_reference(data["benchmark"]),
                    "decision_report": file_reference(data["decision_report"]),
                    "data_health": file_reference(data["data_health"]),
                },
                "data_manifests": data["manifests"],
            },
        )

        state_after = bridge_dir / "pipeline_state_after.json"
        _write_json(
            state_after,
            {
                "schema_version": 1,
                "last_successful_as_of": config.as_of.isoformat(),
                "git_sha": git_sha,
                "validation_anchor": dict(state["validation_anchor"]),
                "membership": _reference(config.membership),
                "comparison": _reference(config.comparison),
                "current_universe": _reference(data["current_universe"]),
                "benchmark": _reference(data["benchmark"]),
                "decision_report": _reference(data["decision_report"]),
                "data_health": _reference(data["data_health"]),
                "account": {**file_reference(account_after), "path": str(config.account.resolve())},
                "epoch_bridge": file_reference(bridge_manifest),
                "manifests": data["manifests"],
            },
        )

        anchor_manifest = create_validation_anchor(
            account=account_after,
            pipeline_state=state_after,
            formal_run_manifest=formal_run_manifest.resolve(),
            comparison=config.comparison.resolve(),
            benchmark=data["benchmark"],
            output_root=validation_root,
            created_at=timestamp,
            git_sha=git_sha,
            supersedes={**supersedes, "epoch_bridge": file_reference(bridge_manifest)},
        )
        anchor = load_verified_anchor(anchor_manifest)
        anchor_account = verify_file_reference(anchor["artifacts"]["account"])  # type: ignore[index]

        _copy_file_atomic(account_after, config.account)
        account_published = True
        if sha256_file(config.account) != sha256_file(anchor_account):
            raise ValueError("published paper account differs from the anchor snapshot")
        anchor_reference = file_reference(anchor_manifest)
        _write_state_atomic(
            config.state,
            {
                **_load_json(state_after),
                "validation_anchor": anchor_reference,
                "evidence_parent": anchor_reference,
            },
        )
    except BaseException:
        if account_published:
            _copy_file_atomic(bridge_dir / "account_before.json", config.account)
        if anchor_manifest is not None:
            shutil.rmtree(anchor_manifest.parent, ignore_errors=True)
        shutil.rmtree(bridge_dir, ignore_errors=True)
        raise

    return {
        "status": "bridged",
        "from_as_of": previous_as_of.isoformat(),
        "to_as_of": config.as_of.isoformat(),
        "bridge_manifest": str(bridge_manifest),
        "anchor_manifest": str(anchor_manifest),
        "cancelled_target_count": len(cancelled["targets"]),
        "counts_toward_evidence": False,
    }


def _require_all_cash(account: Mapping[str, object]) -> None:
    for name in EMPTY_ACCOUNT_BOOKS:
        if account.get(name):
            raise ValueError(f"epoch bridge requires an empty {name.replace('_', ' ')} book")
    regime = account.get("drawdown_control_state")
    if not isinstance(regime, Mapping) or regime.get("regime") != "normal":
        raise ValueError("epoch bridge requires the normal drawdown regime")


def _superseded_references(
    state: Mapping[str, object],
    *,
    account: Path,
    validation_anchor: Path,
    evidence_parent: Path,
) -> dict[str, dict[str, object]]:
    supersedes: dict[str, dict[str, object]] = {
        "validation_anchor": dict(state["validation_anchor"]),  # type: ignore[arg-type]
    }
    if evidence_parent == validation_anchor:
        return supersedes
    cycle_reference = _verified_latest_cycle_reference(
        state,
        account=account,
        validation_anchor=validation_anchor,
    )
    supersedes["cycle_manifest"] = cycle_reference
    report_reference = _optional_verified_latest_report_reference(
        state,
        validation_anchor=validation_anchor,
        latest_cycle=verify_file_reference(cycle_reference),
    )
    if report_reference is not None:
        supersedes["validation_report"] = report_reference
    return supersedes


def _collect_bridge_data(
    config: PipelineConfig,
    *,
    runner: Runner,
    bridge_dir: Path,
    start: date,
    parent_manifests: Mapping[str, Mapping[str, Path]],
) -> dict[str, object]:
    date_token = config.as_of.strftime("%Y%m%d")
    current_universe = bridge_dir / "current_universe.csv"
    benchmark = bridge_dir / "csi300_market_state.csv"
    decision_report = bridge_dir / "decision_report.json"
    data_health = bridge_dir / "data_health.json"

    runner(
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
        runner=runner,
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
        runner=runner,
        label="execution-price",
        date_token=date_token,
        start=start,
        parent=parent_manifests["execution_price"]["raw_manifest"],
        adjust="none",
        source="akshare-tencent",
        workers=8,
    )
    runner(
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
    _require_final_session(benchmark, config.as_of)
    factor_raw, factor_processed = _factor_stage(
        config,
        runner=runner,
        date_token=date_token,
        start=start,
        parent=parent_manifests["factor"]["raw_manifest"],
        benchmark=benchmark,
        signal_features=signal_processed.parent / "features.csv",
    )
    action_raw, action_processed = _action_stage(
        config,
        runner=runner,
        date_token=date_token,
        start=start,
        parent=parent_manifests["corporate_action"]["raw_manifest"],
    )
    runner(
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
    _require_file(decision_report, "bridge decision report")
    if _load_json(data_health).get("passed") is not True:
        raise ValueError("bridge data health did not pass")
    return {
        "current_universe": current_universe,
        "benchmark": benchmark,
        "decision_report": decision_report,
        "data_health": data_health,
        "manifests": {
            "signal_price": _manifest_state(signal_raw, signal_processed),
            "execution_price": _manifest_state(execution_raw, execution_processed),
            "factor": _manifest_state(factor_raw, factor_processed),
            "corporate_action": _manifest_state(action_raw, action_processed),
        },
    }


def _require_final_session(benchmark: Path, as_of: date) -> None:
    with benchmark.open(encoding="utf-8", newline="") as handle:
        dates = [str(row["trade_date"]) for row in csv.DictReader(handle)]
    if not dates or dates[-1] != as_of.isoformat():
        raise ValueError(f"bridge end date {as_of.isoformat()} is not the latest CSI 300 session")


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bridge an all-cash CSI 300 paper account into a new non-counted epoch."
    )
    parser.add_argument(
        "--as-of", required=True, help="Last completed CSI 300 session to bridge to."
    )
    parser.add_argument("--state", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--membership", required=True)
    parser.add_argument("--comparison", required=True)
    parser.add_argument("--formal-run-manifest", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--validation-root", default="data/paper/csi300_baseline/validation")
    parser.add_argument("--raw-price-root", default="data/diagnostics/raw-price-runs")
    parser.add_argument("--processed-price-root", default="data/diagnostics/processed-price-runs")
    parser.add_argument("--raw-factor-root", default="data/diagnostics/raw-factor-runs")
    parser.add_argument("--processed-factor-root", default="data/diagnostics/processed-factor-runs")
    parser.add_argument("--raw-action-root", default="data/diagnostics/raw-corporate-action-runs")
    parser.add_argument(
        "--processed-action-root", default="data/diagnostics/processed-corporate-action-runs"
    )
    parser.add_argument("--benchmark-start", default="2020-06-01")
    parser.add_argument("--created-at", default=None)
    parser.add_argument("--constituent-timeout", type=int, default=60)
    parser.add_argument("--stage-timeout", type=int, default=3600)
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
        cycle_root=Path("outputs/paper_trading/csi300_baseline/cycles"),
        benchmark_start=date.fromisoformat(args.benchmark_start),
        constituent_timeout=args.constituent_timeout,
        stage_timeout=args.stage_timeout,
    )
    result = run_bridge(
        config,
        formal_run_manifest=Path(args.formal_run_manifest),
        validation_root=Path(args.validation_root),
        reason=args.reason,
        created_at=args.created_at,
    )
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
