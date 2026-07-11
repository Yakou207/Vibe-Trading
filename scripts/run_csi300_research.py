from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.data.historical_universe import load_membership_intervals  # noqa: E402
from fintech_quant.data.run_artifacts import sha256_file  # noqa: E402
from fintech_quant.reports import (  # noqa: E402
    build_factor_analysis_report,
    build_scoring_coverage_report,
    compare_strategy_reports,
    write_comparison_report,
    write_factor_analysis_report,
)
from fintech_quant.research import (  # noqa: E402
    ResearchRunConfig,
    run_research_baseline,
    write_run_report,
)
from fintech_quant.research.data_health import (  # noqa: E402
    DataHealthThresholds,
    validate_research_data,
)
from fintech_quant.research.dataset import load_research_dataset  # noqa: E402
from fintech_quant.research.scoring import build_score_inputs, build_stock_scores  # noqa: E402
from fintech_quant.training import build_rl_state_samples, write_rl_state_jsonl  # noqa: E402


@dataclass(frozen=True)
class VerifiedInputs:
    membership: Path
    fundamentals: Path
    capital_flow: Path
    trading_calendar_sha256: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the formal point-in-time CSI 300 research chain."
    )
    parser.add_argument("--processed-manifest", required=True)
    parser.add_argument("--features", required=True)
    parser.add_argument("--execution-price-manifest", required=True)
    parser.add_argument("--corporate-action-manifest", required=True)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--information", default=None)
    parser.add_argument("--dqn-diagnostics", default=None)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--index-code", default="000300")
    parser.add_argument("--output-root", default="outputs/csi300_research")
    parser.add_argument("--created-at", default=None)
    parser.add_argument("--expected-members", type=int, default=300)
    parser.add_argument("--minimum-price-coverage", type=float, default=0.95)
    parser.add_argument("--minimum-fundamental-coverage", type=float, default=0.80)
    parser.add_argument("--minimum-capital-flow-coverage", type=float, default=0.95)
    parser.add_argument("--fundamental-warmup-days", type=int, default=180)
    parser.add_argument("--maximum-fundamental-age-days", type=int, default=180)
    parser.add_argument("--maximum-capital-flow-age-sessions", type=int, default=3)
    parser.add_argument("--initial-cash", type=float, default=100000.0)
    parser.add_argument("--max-position-weight", type=float, default=0.08)
    parser.add_argument("--commission-rate", type=float, default=0.0003)
    parser.add_argument("--minimum-commission", type=float, default=5.0)
    parser.add_argument("--slippage-rate", type=float, default=0.0005)
    parser.add_argument("--buy-threshold", type=float, default=70.0)
    parser.add_argument("--min-score-confidence", type=float, default=0.8)
    args = parser.parse_args()

    processed_manifest_path = Path(args.processed_manifest).resolve()
    features_path = Path(args.features).resolve()
    execution_price_manifest_path = Path(args.execution_price_manifest).resolve()
    corporate_action_manifest_path = Path(args.corporate_action_manifest).resolve()
    execution_prices_path = _resolve_processed_artifact(
        execution_price_manifest_path,
        "daily.csv",
        required_request={"adjust": "none"},
    )
    corporate_actions_path = _resolve_processed_artifact(
        corporate_action_manifest_path,
        "corporate_actions.csv",
    )
    benchmark_path = Path(args.benchmark).resolve()
    information_path = Path(args.information).resolve() if args.information else None
    diagnostics_path = Path(args.dqn_diagnostics).resolve() if args.dqn_diagnostics else None
    inputs = _resolve_verified_inputs(processed_manifest_path)
    membership_path = inputs.membership
    fundamentals_path = inputs.fundamentals
    capital_flow_path = inputs.capital_flow
    if sha256_file(benchmark_path) != inputs.trading_calendar_sha256:
        raise ValueError("benchmark hash does not match the processed trading calendar")

    run_dir = Path(args.output_root).resolve() / args.run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    universe_path = run_dir / "universe.csv"
    _write_universe(universe_path, membership_path, expected_index_code=args.index_code)
    dataset = load_research_dataset(
        features_path,
        universe_path,
        fundamentals_path=fundamentals_path,
        capital_flow_path=capital_flow_path,
        market_state_path=benchmark_path,
        information_path=information_path,
        membership_path=membership_path,
        require_point_in_time=True,
    )
    health = validate_research_data(
        dataset,
        thresholds=DataHealthThresholds(
            expected_members=args.expected_members,
            minimum_price_coverage=args.minimum_price_coverage,
            minimum_fundamental_coverage=args.minimum_fundamental_coverage,
            minimum_capital_flow_coverage=args.minimum_capital_flow_coverage,
            fundamental_warmup_days=args.fundamental_warmup_days,
            maximum_fundamental_age_days=args.maximum_fundamental_age_days,
            maximum_capital_flow_age_sessions=args.maximum_capital_flow_age_sessions,
        ),
    )
    health_path = run_dir / "data_health.json"
    _write_json(health_path, health.to_json())
    if not health.passed:
        print(f"data_health={health_path}", file=sys.stderr)
        print(f"issue_count={len(health.issues)}", file=sys.stderr)
        return 2

    scores = build_stock_scores(dataset)
    _write_json(run_dir / "scoring_coverage.json", build_scoring_coverage_report(scores))
    write_factor_analysis_report(
        run_dir / "stock_score_analysis.json",
        build_factor_analysis_report(scores, build_score_inputs(dataset)),
    )

    common_config = {
        "features_path": features_path,
        "execution_prices_path": execution_prices_path,
        "corporate_actions_path": corporate_actions_path,
        "universe_path": universe_path,
        "information_path": information_path,
        "fundamentals_path": fundamentals_path,
        "capital_flow_path": capital_flow_path,
        "market_state_path": benchmark_path,
        "membership_path": membership_path,
        "require_point_in_time": True,
        "initial_cash": args.initial_cash,
        "max_position_weight": args.max_position_weight,
        "commission_rate": args.commission_rate,
        "minimum_commission": args.minimum_commission,
        "slippage_rate": args.slippage_rate,
        "execution_delay_sessions": 1,
        "buy_threshold": args.buy_threshold,
        "min_score_confidence": args.min_score_confidence,
    }
    baseline_report = run_research_baseline(
        ResearchRunConfig(run_id="baseline", max_portfolio_drawdown=1.0, **common_config)
    )
    risk_report = run_research_baseline(
        ResearchRunConfig(run_id="risk_controlled", max_portfolio_drawdown=0.10, **common_config)
    )
    baseline_path = write_run_report(baseline_report, run_dir)
    risk_path = write_run_report(risk_report, run_dir)

    rl_path = run_dir / "rl_state_dataset.jsonl"
    write_rl_state_jsonl(rl_path, build_rl_state_samples(dataset))
    comparison = compare_strategy_reports(
        _read_json(baseline_path),
        _read_json(risk_path),
        benchmark_curves={"CSI 300": _read_csv(benchmark_path)},
    )
    write_comparison_report(run_dir / "benchmark_comparison.json", comparison)

    manifest_path = run_dir / "manifest.json"
    _write_json(
        manifest_path,
        {
            "run_id": args.run_id,
            "created_at": args.created_at or datetime.now(timezone.utc).isoformat(),
            "git_sha": _git_sha(),
            "data_health_passed": True,
            "dqn_overlay_status": _dqn_status(diagnostics_path),
            "research_scope": {
                "index_code": args.index_code,
                "expected_members": args.expected_members,
                "execution_timing": "signal_t_executes_at_next_available_session_open",
                "risk_control_note": (
                    "10% liquidation gate; cross-backend 8% exposure reduction remains "
                    "a later validation phase"
                ),
            },
            "inputs": {
                name: _file_reference(path)
                for name, path in {
                    "processed_manifest": processed_manifest_path,
                    "membership": membership_path,
                    "features": features_path,
                    "execution_price_manifest": execution_price_manifest_path,
                    "execution_prices": execution_prices_path,
                    "corporate_action_manifest": corporate_action_manifest_path,
                    "corporate_actions": corporate_actions_path,
                    "fundamentals": fundamentals_path,
                    "capital_flow": capital_flow_path,
                    "benchmark": benchmark_path,
                    "information": information_path,
                    "dqn_diagnostics": diagnostics_path,
                }.items()
                if path is not None
            },
            "artifacts": [
                _artifact_reference(path, run_dir)
                for path in sorted(run_dir.rglob("*"))
                if path.is_file() and path != manifest_path
            ],
        },
    )
    print(f"run_dir={run_dir}")
    print(f"manifest={manifest_path}")
    print("data_health_passed=true")
    return 0


def _resolve_verified_inputs(processed_manifest_path: Path) -> VerifiedInputs:
    processed = _read_json(processed_manifest_path)
    if processed.get("layer") != "processed":
        raise ValueError("--processed-manifest must describe a processed run")
    artifacts = _verified_artifacts(processed_manifest_path, processed)
    required = {name: artifacts.get(f"{name}.csv") for name in ("fundamentals", "capital_flow")}
    if any(path is None for path in required.values()):
        raise ValueError("processed manifest must contain fundamentals.csv and capital_flow.csv")

    raw_value = processed.get("parent_manifest")
    if not isinstance(raw_value, str) or not raw_value:
        raise ValueError("processed manifest must reference its raw parent manifest")
    raw_manifest_path = Path(raw_value).resolve()
    request = processed.get("request")
    if not isinstance(request, Mapping):
        raise ValueError("processed manifest request must be an object")
    if sha256_file(raw_manifest_path) != request.get("parent_manifest_sha256"):
        raise ValueError("raw parent manifest hash mismatch")
    calendar_hash = request.get("trading_calendar_sha256")
    if not isinstance(calendar_hash, str) or not calendar_hash:
        raise ValueError("processed manifest must record its trading calendar hash")
    raw = _read_json(raw_manifest_path)
    if raw.get("layer") != "raw":
        raise ValueError("parent manifest must describe a raw run")
    _verified_artifacts(raw_manifest_path, raw)
    raw_request = raw.get("request")
    if not isinstance(raw_request, Mapping) or not raw_request.get("membership"):
        raise ValueError("raw manifest must record its historical membership file")
    membership_path = Path(str(raw_request["membership"])).resolve()
    if sha256_file(membership_path) != raw_request.get("membership_sha256"):
        raise ValueError("historical membership hash mismatch")
    fundamentals_path = required["fundamentals"]
    capital_flow_path = required["capital_flow"]
    if fundamentals_path is None or capital_flow_path is None:
        raise AssertionError("required processed artifacts were not resolved")
    return VerifiedInputs(
        membership=membership_path,
        fundamentals=fundamentals_path,
        capital_flow=capital_flow_path,
        trading_calendar_sha256=calendar_hash,
    )


def _resolve_processed_artifact(
    manifest_path: Path,
    relative_path: str,
    *,
    required_request: Mapping[str, object] | None = None,
) -> Path:
    manifest = _read_json(manifest_path)
    if manifest.get("layer") != "processed":
        raise ValueError(f"{manifest_path.name} must describe a processed run")
    artifacts = _verified_artifacts(manifest_path, manifest)
    artifact = artifacts.get(relative_path)
    if artifact is None:
        raise ValueError(f"processed manifest must contain {relative_path}")
    request = manifest.get("request")
    if not isinstance(request, Mapping):
        raise ValueError("processed manifest request must be an object")
    for key, expected in (required_request or {}).items():
        if request.get(key) != expected:
            raise ValueError(f"processed manifest request must set {key}={expected}")
    return artifact


def _verified_artifacts(manifest_path: Path, manifest: Mapping[str, object]) -> dict[str, Path]:
    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, list):
        raise ValueError("manifest artifacts must be a list")
    result: dict[str, Path] = {}
    base = manifest_path.parent.resolve()
    for artifact in raw_artifacts:
        if not isinstance(artifact, Mapping):
            raise ValueError("manifest artifacts must contain objects")
        relative = str(artifact.get("path", ""))
        path = (base / relative).resolve()
        if path.parent != base and base not in path.parents:
            raise ValueError("manifest artifact path escapes its run directory")
        if sha256_file(path) != artifact.get("sha256"):
            raise ValueError(f"manifest artifact hash mismatch: {relative}")
        result[relative] = path
    return result


def _write_universe(path: Path, membership_path: Path, *, expected_index_code: str) -> None:
    intervals = load_membership_intervals(membership_path)
    index_codes = {interval.index_code for interval in intervals}
    if index_codes != {expected_index_code}:
        raise ValueError(
            f"membership index code mismatch: expected {expected_index_code}, "
            f"found {sorted(index_codes)}"
        )
    symbols = sorted({interval.symbol for interval in intervals})
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("symbol", "name", "sector"))
        writer.writeheader()
        writer.writerows({"symbol": symbol, "name": "", "sector": ""} for symbol in symbols)


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_csv(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _file_reference(path: Path) -> dict[str, object]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _artifact_reference(path: Path, run_dir: Path) -> dict[str, object]:
    reference = _file_reference(path)
    reference["path"] = str(path.relative_to(run_dir))
    return reference


def _dqn_status(path: Path | None) -> str:
    if path is None:
        return "diagnostic_only"
    diagnostics = _read_json(path)
    if diagnostics.get("backend_parity_passed") is True:
        return "parity_passed"
    return "diagnostic_only"


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
