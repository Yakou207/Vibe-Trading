from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.data.historical_universe import load_membership_intervals  # noqa: E402
from fintech_quant.data.manifest_chain import (  # noqa: E402
    VerifiedManifest,
    load_verified_manifest,
)
from fintech_quant.data.run_artifacts import sha256_file  # noqa: E402
from fintech_quant.research import (  # noqa: E402
    DataHealthThresholds,
    build_daily_decision_report,
    load_research_dataset,
    validate_research_data,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build one fresh, health-gated CSI 300 post-close decision report."
    )
    parser.add_argument("--factor-manifest", required=True)
    parser.add_argument("--signal-price-manifest", required=True)
    parser.add_argument("--execution-price-manifest", required=True)
    parser.add_argument("--corporate-action-manifest", required=True)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--membership", required=True)
    parser.add_argument("--information", default=None)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--data-health-output", required=True)
    parser.add_argument("--index-code", default="000300")
    parser.add_argument("--expected-members", type=int, default=300)
    parser.add_argument("--minimum-price-coverage", type=float, default=0.95)
    parser.add_argument("--minimum-fundamental-coverage", type=float, default=0.80)
    parser.add_argument("--minimum-capital-flow-coverage", type=float, default=0.95)
    parser.add_argument("--fundamental-warmup-days", type=int, default=180)
    parser.add_argument("--maximum-fundamental-age-days", type=int, default=180)
    parser.add_argument("--maximum-capital-flow-age-sessions", type=int, default=3)
    parser.add_argument("--created-at", default=None)
    args = parser.parse_args()

    as_of = date.fromisoformat(args.as_of)
    factor_manifest = load_verified_manifest(
        Path(args.factor_manifest), expected_layer="processed"
    )
    signal_manifest = load_verified_manifest(
        Path(args.signal_price_manifest), expected_layer="processed"
    )
    execution_manifest = load_verified_manifest(
        Path(args.execution_price_manifest), expected_layer="processed"
    )
    action_manifest = load_verified_manifest(
        Path(args.corporate_action_manifest), expected_layer="processed"
    )
    features = _required_artifact(signal_manifest, "features.csv")
    execution_prices = _required_artifact(execution_manifest, "daily.csv")
    fundamentals = _required_artifact(factor_manifest, "fundamentals.csv")
    capital_flow = _required_artifact(factor_manifest, "capital_flow.csv")
    corporate_actions = _required_artifact(action_manifest, "corporate_actions.csv")
    _require_request(signal_manifest, "adjust", "qfq")
    _require_request(execution_manifest, "adjust", "none")
    _require_request(action_manifest, "action_types", ["distribution", "rights_issue"])
    action_end = date.fromisoformat(str(_request(action_manifest)["end"]))
    if action_end < as_of:
        raise ValueError(
            f"corporate-action coverage ends {action_end.isoformat()} before {as_of.isoformat()}"
        )
    _require_latest_trade_date(execution_prices, as_of, label="execution prices")

    benchmark = Path(args.benchmark).resolve()
    membership = Path(args.membership).resolve()
    if sha256_file(benchmark) != _request(factor_manifest).get("trading_calendar_sha256"):
        raise ValueError("factor trading-calendar hash does not match benchmark")
    intervals = load_membership_intervals(membership)
    index_codes = {interval.index_code for interval in intervals}
    if index_codes != {args.index_code}:
        raise ValueError(
            f"membership index code mismatch: expected {args.index_code}, "
            f"found {sorted(index_codes)}"
        )

    with tempfile.TemporaryDirectory(prefix="csi300-daily-decision-") as tmp:
        universe = Path(tmp) / "universe.csv"
        _write_universe(universe, sorted({interval.symbol for interval in intervals}))
        dataset = load_research_dataset(
            features,
            universe,
            fundamentals_path=fundamentals,
            capital_flow_path=capital_flow,
            market_state_path=benchmark,
            information_path=Path(args.information).resolve() if args.information else None,
            membership_path=membership,
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
    health_output = Path(args.data_health_output)
    _write_json(health_output, health.to_json())
    input_refs = {
        "factor_manifest": _file_reference(factor_manifest.path),
        "signal_price_manifest": _file_reference(signal_manifest.path),
        "execution_price_manifest": _file_reference(execution_manifest.path),
        "corporate_action_manifest": _file_reference(action_manifest.path),
        "features": _file_reference(features),
        "execution_prices": _file_reference(execution_prices),
        "fundamentals": _file_reference(fundamentals),
        "capital_flow": _file_reference(capital_flow),
        "corporate_actions": _file_reference(corporate_actions),
        "benchmark": _file_reference(benchmark),
        "membership": _file_reference(membership),
    }
    if args.information:
        input_refs["information"] = _file_reference(Path(args.information).resolve())
    report = build_daily_decision_report(
        dataset,
        as_of=as_of,
        data_health=health,
        expected_members=args.expected_members,
        input_refs=input_refs,
    )
    report["created_at"] = args.created_at or datetime.now(timezone.utc).isoformat()
    report["git_sha"] = _git_sha()
    output = Path(args.output)
    _write_json(output, report)
    print(f"decision_report={output}")
    print(f"data_health={health_output}")
    print(f"score_count={len(report['scores'])}")
    print(f"risk_warning_count={len(report['risk_warnings'])}")
    return 0


def _required_artifact(manifest: VerifiedManifest, relative: str) -> Path:
    path = manifest.artifacts.get(relative)
    if path is None:
        raise ValueError(f"processed manifest must contain {relative}")
    return path


def _request(manifest: VerifiedManifest) -> Mapping[str, object]:
    request = manifest.payload.get("request", {})
    if not isinstance(request, Mapping):
        raise ValueError("processed manifest request must be an object")
    return request


def _require_request(manifest: VerifiedManifest, key: str, expected: object) -> None:
    if _request(manifest).get(key) != expected:
        raise ValueError(f"processed manifest request must set {key}={expected}")


def _require_latest_trade_date(path: Path, as_of: date, *, label: str) -> None:
    with path.open(encoding="utf-8", newline="") as handle:
        dates = [
            date.fromisoformat(str(row["trade_date"]))
            for row in csv.DictReader(handle)
            if row.get("trade_date")
        ]
    if not dates:
        raise ValueError(f"{label} contain no trade dates")
    latest = max(dates)
    if latest != as_of:
        raise ValueError(
            f"latest {label} date {latest.isoformat()} does not match as_of {as_of.isoformat()}"
        )


def _write_universe(path: Path, symbols: list[str]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("symbol", "name", "sector"))
        writer.writeheader()
        writer.writerows({"symbol": symbol, "name": "", "sector": ""} for symbol in symbols)


def _file_reference(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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
