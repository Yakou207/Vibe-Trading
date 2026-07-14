from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from fintech_quant.execution.paper_evidence import (
    approved_paper_policy,
    canonical_json_sha256,
    file_reference,
)
from fintech_quant.reports.paper_validation import audit_paper_validation


def test_audit_reports_no_evidence_for_anchor_only(tmp_path: Path) -> None:
    anchor = _write_anchor(tmp_path, as_of=date(2026, 1, 2), equity=100000.0)

    report = audit_paper_validation(anchor, [])

    assert report["status"] == "NO_EVIDENCE"
    assert report["metrics"]["valid_sessions"] == 0
    assert report["gates"]["live_trading_disabled"]["passed"] is True


def test_audit_rejects_broken_account_chain(tmp_path: Path) -> None:
    anchor, cycles = _write_passing_series(tmp_path, sessions=2, span_days=2)
    payload = _load_json(cycles[1])
    payload["account_before_sha256"] = "wrong"
    _write_json(cycles[1], payload)

    with pytest.raises(ValueError, match="account hash chain"):
        audit_paper_validation(anchor, cycles)


@pytest.mark.parametrize(
    ("sessions", "span_days", "expected_status"),
    [(39, 56, "COLLECTING"), (40, 55, "COLLECTING"), (40, 56, "ELIGIBLE_FOR_REVIEW")],
)
def test_duration_boundaries(
    tmp_path: Path, sessions: int, span_days: int, expected_status: str
) -> None:
    anchor, cycles = _write_passing_series(
        tmp_path,
        sessions=sessions,
        span_days=span_days,
    )

    report = audit_paper_validation(anchor, cycles)

    assert report["status"] == expected_status


def test_completed_window_above_ten_percent_drawdown_fails(tmp_path: Path) -> None:
    anchor, cycles = _write_passing_series(
        tmp_path,
        sessions=40,
        span_days=56,
        drawdown=0.1001,
    )

    report = audit_paper_validation(anchor, cycles)

    assert report["status"] == "FAILED"
    assert report["gates"]["maximum_drawdown"]["passed"] is False


def test_completed_window_without_positive_excess_fails(tmp_path: Path) -> None:
    anchor, cycles = _write_passing_series(
        tmp_path,
        sessions=40,
        span_days=56,
        paper_return=0.01,
        benchmark_return=0.02,
    )

    report = audit_paper_validation(anchor, cycles)

    assert report["status"] == "FAILED"
    assert report["gates"]["positive_excess_return"]["passed"] is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"data_health_passed": False}, "data health"),
        ({"dqn_exposure_enabled": True}, "DQN exposure"),
        ({"live_trading_enabled": True}, "live trading"),
        ({"blocked_reason": "missing_price"}, "execution anomaly"),
        ({"walk_forward_excess": [0.1, -0.01, 0.2, 0.1]}, "walk-forward"),
    ],
)
def test_mandatory_integrity_and_strategy_gates_fail(
    tmp_path: Path, mutation: dict[str, object], message: str
) -> None:
    anchor, cycles = _write_passing_series(
        tmp_path,
        sessions=40,
        span_days=56,
        **mutation,
    )

    report = audit_paper_validation(anchor, cycles)

    assert report["status"] == "FAILED"
    assert message in " ".join(report["failures"])


def test_allowed_market_constraint_blocks_are_counted(tmp_path: Path) -> None:
    anchor, cycles = _write_passing_series(
        tmp_path,
        sessions=40,
        span_days=56,
        blocked_reason="limit_down",
    )

    report = audit_paper_validation(anchor, cycles)

    assert report["status"] == "ELIGIBLE_FOR_REVIEW"
    assert report["metrics"]["constraint_blocks"] == {"limit_down": 1}


def test_v1_cycles_never_count_as_validation_evidence(tmp_path: Path) -> None:
    anchor = _write_anchor(tmp_path, as_of=date(2026, 1, 2), equity=100000.0)
    v1 = tmp_path / "cycles/2026-01-03/cycle_manifest.json"
    _write_json(v1, {"schema_version": 1, "as_of": "2026-01-03"})

    report = audit_paper_validation(anchor, [v1])

    assert report["status"] == "NO_EVIDENCE"
    assert report["metrics"]["valid_sessions"] == 0


def test_missing_expected_benchmark_session_fails(tmp_path: Path) -> None:
    anchor, cycles = _write_passing_series(tmp_path, sessions=2, span_days=3)
    latest = _load_json(cycles[-1])
    benchmark = Path(latest["inputs"]["benchmark"]["path"])
    _write_benchmark(
        benchmark,
        {
            date(2026, 1, 1): 4000.0,
            date(2026, 1, 2): 4001.0,
            date(2026, 1, 3): 4002.0,
            date(2026, 1, 4): 4003.0,
        },
    )
    latest["inputs"]["benchmark"] = file_reference(benchmark)
    decision = Path(latest["inputs"]["research_report"]["path"])
    decision_payload = _load_json(decision)
    decision_payload["inputs"]["benchmark"] = file_reference(benchmark)
    _write_json(decision, decision_payload)
    latest["inputs"]["research_report"] = file_reference(decision)
    _write_json(cycles[-1], latest)

    report = audit_paper_validation(anchor, cycles)

    assert report["status"] == "FAILED"
    assert report["gates"]["expected_session_continuity"]["passed"] is False


def test_trade_price_must_match_next_open_and_approved_slippage(tmp_path: Path) -> None:
    anchor, cycles = _write_passing_series(
        tmp_path,
        sessions=40,
        span_days=56,
        final_trade_price=10.0,
    )

    report = audit_paper_validation(anchor, cycles)

    assert report["status"] == "FAILED"
    assert "execution anomaly for trade price" in " ".join(report["failures"])


def test_decision_report_requires_complete_material_input_evidence(tmp_path: Path) -> None:
    anchor, cycles = _write_passing_series(tmp_path, sessions=2, span_days=2)
    manifest = _load_json(cycles[-1])
    decision = Path(manifest["inputs"]["research_report"]["path"])
    decision_payload = _load_json(decision)
    decision_payload["inputs"] = {"source_data": next(iter(decision_payload["inputs"].values()))}
    _write_json(decision, decision_payload)
    manifest["inputs"]["research_report"] = file_reference(decision)
    _write_json(cycles[-1], manifest)

    with pytest.raises(ValueError, match="decision inputs.*missing"):
        audit_paper_validation(anchor, cycles)


def _write_passing_series(
    root: Path,
    *,
    sessions: int,
    span_days: int,
    paper_return: float = 0.10,
    benchmark_return: float = 0.02,
    drawdown: float = 0.0,
    data_health_passed: bool = True,
    dqn_exposure_enabled: bool = False,
    live_trading_enabled: bool = False,
    blocked_reason: str | None = None,
    walk_forward_excess: list[float] | None = None,
    final_trade_price: float | None = None,
) -> tuple[Path, list[Path]]:
    if sessions <= 0 or span_days < sessions:
        raise ValueError("fixture requires at least one calendar day per session")
    anchor_date = date(2026, 1, 1)
    anchor_equity = 100000.0
    anchor = _write_anchor(
        root,
        as_of=anchor_date,
        equity=anchor_equity,
        walk_forward_excess=walk_forward_excess,
    )
    session_dates = _session_dates(anchor_date, sessions, span_days)
    equities = [
        anchor_equity * (1.0 + paper_return * (index + 1) / sessions)
        for index in range(sessions)
    ]
    if drawdown:
        equities[0] = anchor_equity
        equities[1] = anchor_equity * (1.0 - drawdown)
    benchmark_values = {
        anchor_date: 4000.0,
        **{
            trade_date: 4000.0 * (1.0 + benchmark_return * (index + 1) / sessions)
            for index, trade_date in enumerate(session_dates)
        },
    }
    current_universe = root / "inputs/current_universe.csv"
    _write_universe(current_universe)
    membership = root / "inputs/membership.csv"
    _write_membership(membership)
    source = root / "inputs/source_manifest.json"
    _write_json(source, {"verified": True})
    processed_manifests = {
        name: _write_processed_manifest(root / "inputs" / name / "manifest.json")
        for name in (
            "factor_manifest",
            "signal_price_manifest",
            "execution_price_manifest",
            "corporate_action_manifest",
        )
    }
    cycles: list[Path] = []
    previous_record = anchor
    previous_account_sha = file_reference(
        Path(_load_json(anchor)["artifacts"]["account"]["path"])
    )["sha256"]
    for index, (trade_date, equity) in enumerate(zip(session_dates, equities, strict=True)):
        cycle_dir = root / "cycles" / trade_date.isoformat()
        benchmark = cycle_dir / "benchmark.csv"
        _write_benchmark(
            benchmark,
            {key: value for key, value in benchmark_values.items() if key <= trade_date},
        )
        health = cycle_dir / "data_health.json"
        health_payload = {
            "passed": data_health_passed,
            "metrics": {
                "fundamental_stale_count": 0,
                "capital_flow_stale_count": 0,
                "future_leakage_count": 0,
            },
            "issues": [],
        }
        _write_json(health, health_payload)
        execution_prices = cycle_dir / "execution_prices.csv"
        execution_prices.write_text(
            "symbol,trade_date,open,close\n"
            f"000001.SZ,{trade_date.isoformat()},10,10\n",
            encoding="utf-8",
        )
        comparison = Path(_load_json(anchor)["artifacts"]["comparison"]["path"])
        actions = cycle_dir / "corporate_actions.csv"
        actions.write_text("symbol,ex_date,action_type\n", encoding="utf-8")
        decision = cycle_dir / "decision_report.json"
        _write_json(
            decision,
            {
                "as_of": trade_date.isoformat(),
                "data_health_passed": data_health_passed,
                "data_health": health_payload,
                "inputs": {
                    **{
                        name: file_reference(path)
                        for name, path in processed_manifests.items()
                    },
                    "features": file_reference(source),
                    "execution_prices": file_reference(execution_prices),
                    "fundamentals": file_reference(source),
                    "capital_flow": file_reference(source),
                    "corporate_actions": file_reference(actions),
                    "benchmark": file_reference(benchmark),
                    "membership": file_reference(membership),
                },
                "scores": [],
                "risk_warnings": [],
            },
        )
        targets = cycle_dir / "targets.csv"
        targets.write_text(
            "symbol,raw_target_weight,target_weight,rl_action\n",
            encoding="utf-8",
        )
        positions: dict[str, object] = {}
        cash = equity
        trades: list[dict[str, object]] = []
        if final_trade_price is not None and index == sessions - 1:
            positions = {"000001.SZ": {"shares": 100, "cost_basis": final_trade_price}}
            cash = equity - 1000.0
            trades = [
                {
                    "trade_date": trade_date.isoformat(),
                    "symbol": "000001.SZ",
                    "action": "buy",
                    "price": final_trade_price,
                    "shares": 100,
                    "notional": 100 * final_trade_price,
                    "total_cost": 5.0,
                }
            ]
        account = {
            "cash": cash,
            "positions": positions,
            "nav_history": [{"trade_date": trade_date.isoformat(), "equity": equity}],
            "pending_targets": {},
            "pending_signal_date": trade_date.isoformat(),
            "last_processed_date": trade_date.isoformat(),
        }
        blocked_orders = []
        if blocked_reason is not None and index == sessions - 1:
            blocked_orders = [
                {"symbol": "000001.SZ", "action": "sell", "reason": blocked_reason}
            ]
        paper_report = cycle_dir / "paper_report.json"
        _write_json(
            paper_report,
            {
                "nav": {"trade_date": trade_date.isoformat(), "equity": equity},
                "trades": trades,
                "blocked_orders": blocked_orders,
                "corporate_actions": [],
                "account": account,
            },
        )
        dashboard = cycle_dir / "dashboard.html"
        dashboard.write_text("<html>fixture</html>\n", encoding="utf-8")
        policy = approved_paper_policy()
        policy["dqn_exposure_enabled"] = dqn_exposure_enabled
        policy["live_trading_enabled"] = live_trading_enabled
        manifest = cycle_dir / "cycle_manifest.json"
        account_after_sha = canonical_json_sha256(account)
        _write_json(
            manifest,
            {
                "schema_version": 2,
                "kind": "paper_trading_cycle",
                "as_of": trade_date.isoformat(),
                "git_sha": "fixture",
                "evidence_parent": file_reference(previous_record),
                "account_before_sha256": previous_account_sha,
                "account_after_sha256": account_after_sha,
                "policy": policy,
                "inputs": {
                    "research_report": file_reference(decision),
                    "execution_prices": file_reference(execution_prices),
                    "comparison": file_reference(comparison),
                    "current_universe": file_reference(current_universe),
                    "benchmark": file_reference(benchmark),
                    "corporate_actions": file_reference(actions),
                    "data_health": file_reference(health),
                },
                "artifacts": {
                    "targets": file_reference(targets),
                    "paper_report": file_reference(paper_report),
                    "dashboard": file_reference(dashboard),
                },
            },
        )
        cycles.append(manifest)
        previous_record = manifest
        previous_account_sha = account_after_sha
    return anchor, cycles


def _write_anchor(
    root: Path,
    *,
    as_of: date,
    equity: float,
    walk_forward_excess: list[float] | None = None,
) -> Path:
    anchor_dir = root / "validation" / f"anchor-{as_of.strftime('%Y%m%d')}"
    account = anchor_dir / "account.json"
    _write_json(
        account,
        {
            "cash": equity,
            "positions": {},
            "last_processed_date": as_of.isoformat(),
        },
    )
    state = anchor_dir / "pipeline_state.json"
    _write_json(state, {"last_successful_as_of": as_of.isoformat()})
    formal = anchor_dir / "formal_run_manifest.json"
    _write_json(formal, {"data_health_passed": True})
    comparison = anchor_dir / "benchmark_comparison.json"
    _write_json(
        comparison,
        {
            "walk_forward": [
                {"candidate_benchmark_excess_return": value}
                for value in (walk_forward_excess or [0.1, 0.2, 0.3, 0.4])
            ]
        },
    )
    benchmark = anchor_dir / "benchmark.csv"
    _write_benchmark(benchmark, {as_of: 4000.0})
    manifest = anchor_dir / "anchor_manifest.json"
    _write_json(
        manifest,
        {
            "schema_version": 1,
            "kind": "paper_validation_anchor",
            "as_of": as_of.isoformat(),
            "created_at": "2026-01-02T00:00:00+00:00",
            "git_sha": "fixture",
            "counts_toward_evidence": False,
            "anchor_equity": equity,
            "drawdown_regime": "normal",
            "policy": approved_paper_policy(),
            "artifacts": {
                "account": file_reference(account),
                "pipeline_state": file_reference(state),
                "formal_run_manifest": file_reference(formal),
                "comparison": file_reference(comparison),
                "benchmark": file_reference(benchmark),
            },
            "data_manifests": {},
        },
    )
    return manifest


def _session_dates(anchor_date: date, sessions: int, span_days: int) -> list[date]:
    if sessions == 1:
        return [anchor_date + timedelta(days=span_days)]
    first = anchor_date + timedelta(days=1)
    return [
        first + timedelta(days=round(index * (span_days - 1) / (sessions - 1)))
        for index in range(sessions)
    ]


def _write_universe(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("symbol", "name"))
        writer.writeheader()
        for value in range(1, 301):
            writer.writerow({"symbol": f"{value:06d}.SZ", "name": "fixture"})


def _write_membership(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "index_code",
                "symbol",
                "member_from",
                "member_to",
                "source",
                "source_fetched_at",
            ),
        )
        writer.writeheader()
        for value in range(1, 301):
            writer.writerow(
                {
                    "index_code": "000300",
                    "symbol": f"{value:06d}.SZ",
                    "member_from": "2020-01-01",
                    "member_to": "",
                    "source": "fixture",
                    "source_fetched_at": "2026-01-01T00:00:00Z",
                }
            )


def _write_processed_manifest(path: Path) -> Path:
    artifact = path.parent / "artifact.txt"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("fixture\n", encoding="utf-8")
    _write_json(
        path,
        {
            "run_id": path.parent.name,
            "layer": "processed",
            "parent_manifest": None,
            "request": {},
            "scopes": [],
            "artifacts": [
                {
                    "path": artifact.name,
                    "bytes": artifact.stat().st_size,
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                }
            ],
        },
    )
    return path


def _write_benchmark(path: Path, values: dict[date, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("trade_date", "index_close"))
        writer.writeheader()
        for trade_date, value in sorted(values.items()):
            writer.writerow({"trade_date": trade_date.isoformat(), "index_close": value})


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
