from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence

from fintech_quant.backtesting.costs import AShareCostModel
from fintech_quant.data.historical_universe import active_symbols, load_membership_intervals
from fintech_quant.data.manifest_chain import load_verified_manifest
from fintech_quant.execution.paper_evidence import (
    approved_paper_policy,
    canonical_json_sha256,
    file_reference,
    load_verified_anchor,
    verify_file_reference,
)


_REQUIRED_INPUTS = (
    "research_report",
    "execution_prices",
    "comparison",
    "current_universe",
    "benchmark",
    "corporate_actions",
    "data_health",
)
_REQUIRED_ARTIFACTS = ("targets", "paper_report", "dashboard")
_REQUIRED_DECISION_INPUTS = (
    "factor_manifest",
    "signal_price_manifest",
    "execution_price_manifest",
    "corporate_action_manifest",
    "features",
    "execution_prices",
    "fundamentals",
    "capital_flow",
    "corporate_actions",
    "benchmark",
    "membership",
)
_ALLOWED_BLOCK_REASONS = {"suspended", "limit_up", "limit_down", "t_plus_one"}


def audit_paper_validation(
    anchor: Path,
    cycle_manifests: Sequence[Path],
    *,
    minimum_sessions: int = 40,
    minimum_calendar_days: int = 56,
    maximum_drawdown: float = 0.10,
) -> dict[str, object]:
    if minimum_sessions <= 0 or minimum_calendar_days <= 0:
        raise ValueError("validation duration thresholds must be positive")
    if not 0.0 <= maximum_drawdown <= 1.0:
        raise ValueError("maximum_drawdown must be between zero and one")

    anchor = anchor.resolve()
    anchor_payload = load_verified_anchor(anchor)
    anchor_date = date.fromisoformat(str(anchor_payload["as_of"]))
    anchor_equity = float(anchor_payload["anchor_equity"])
    if anchor_equity <= 0:
        raise ValueError("paper validation anchor equity must be positive")
    anchor_artifacts = _mapping(anchor_payload.get("artifacts"), "anchor artifacts")
    anchor_account = _mapping(anchor_artifacts.get("account"), "anchor account")
    previous_account_sha = str(anchor_account.get("sha256", ""))
    anchor_comparison = _mapping(
        anchor_artifacts.get("comparison"), "anchor comparison"
    )
    anchor_comparison_sha = str(anchor_comparison.get("sha256", ""))
    walk_forward_excess = _walk_forward_excess(anchor_artifacts)
    walk_forward_passed = bool(walk_forward_excess) and all(
        value > 0 for value in walk_forward_excess
    )

    cycles = _load_v2_cycles(cycle_manifests, anchor_date=anchor_date)
    if not cycles:
        return _empty_report(
            anchor=anchor,
            anchor_date=anchor_date,
            anchor_equity=anchor_equity,
            walk_forward_excess=walk_forward_excess,
            walk_forward_passed=walk_forward_passed,
            minimum_sessions=minimum_sessions,
            minimum_calendar_days=minimum_calendar_days,
            maximum_drawdown=maximum_drawdown,
        )

    failures: list[str] = []
    if not walk_forward_passed:
        failures.append("anchored formal walk-forward excess is not positive in every segment")
    equities = [anchor_equity]
    total_notional = 0.0
    total_cost = 0.0
    trade_count = 0
    constraint_blocks: Counter[str] = Counter()
    all_health_passed = True
    all_reproducible = True
    all_execution_valid = True
    all_policy_approved = True
    dqn_disabled = True
    live_disabled = True
    previous_record = anchor

    for manifest_path, payload, cycle_date in cycles:
        parent = _mapping(payload.get("evidence_parent"), "cycle evidence parent")
        parent_path = verify_file_reference(parent)
        if parent_path != previous_record:
            raise ValueError(
                f"cycle evidence parent chain is broken at {cycle_date.isoformat()}"
            )
        if payload.get("account_before_sha256") != previous_account_sha:
            raise ValueError(
                f"paper account hash chain is broken at {cycle_date.isoformat()}"
            )

        inputs = _verified_references(payload, "inputs", _REQUIRED_INPUTS)
        artifacts = _verified_references(payload, "artifacts", _REQUIRED_ARTIFACTS)
        if file_reference(inputs["comparison"])["sha256"] != anchor_comparison_sha:
            all_reproducible = False
            failures.append(f"{cycle_date}: anchored formal comparison changed")
        if "dqn_report" in _mapping(payload.get("inputs"), "cycle inputs"):
            dqn_disabled = False
            failures.append(f"{cycle_date}: DQN exposure input is present")

        policy = _mapping(payload.get("policy"), "cycle policy")
        if policy != approved_paper_policy():
            all_policy_approved = False
            failures.append(f"{cycle_date}: approved paper policy changed")
        if policy.get("dqn_exposure_enabled") is not False:
            dqn_disabled = False
            failures.append(f"{cycle_date}: DQN exposure is enabled")
        if policy.get("live_trading_enabled") is not False:
            live_disabled = False
            failures.append(f"{cycle_date}: live trading is enabled")

        cycle_result = _audit_cycle(
            cycle_date,
            inputs=inputs,
            artifacts=artifacts,
            account_after_sha256=str(payload.get("account_after_sha256", "")),
            maximum_position_weight=float(
                approved_paper_policy()["maximum_position_weight"]
            ),
        )
        failures.extend(cycle_result["failures"])
        all_health_passed = all_health_passed and bool(cycle_result["health_passed"])
        all_reproducible = all_reproducible and bool(cycle_result["reproducible"])
        all_execution_valid = all_execution_valid and bool(
            cycle_result["execution_valid"]
        )
        equities.append(float(cycle_result["equity"]))
        total_notional += float(cycle_result["notional"])
        total_cost += float(cycle_result["cost"])
        trade_count += int(cycle_result["trade_count"])
        constraint_blocks.update(cycle_result["constraint_blocks"])
        previous_account_sha = str(payload["account_after_sha256"])
        previous_record = manifest_path

    cycle_dates = [item[2] for item in cycles]
    expected_dates = _benchmark_dates(
        _latest_input_path(cycles[-1][1], "benchmark"),
        after=anchor_date,
        through=cycle_dates[-1],
    )
    session_continuity = cycle_dates == expected_dates
    if not session_continuity:
        missing = sorted(set(expected_dates) - set(cycle_dates))
        extra = sorted(set(cycle_dates) - set(expected_dates))
        failures.append(
            "missing expected CSI 300 sessions: "
            f"missing={[value.isoformat() for value in missing]} "
            f"extra={[value.isoformat() for value in extra]}"
        )
        all_reproducible = False

    benchmark_start, benchmark_end = _benchmark_endpoints(
        _latest_input_path(cycles[-1][1], "benchmark"),
        start=anchor_date,
        end=cycle_dates[-1],
    )
    paper_return = equities[-1] / anchor_equity - 1.0
    benchmark_return = benchmark_end / benchmark_start - 1.0
    excess_return = paper_return - benchmark_return
    observed_drawdown = _maximum_drawdown(equities)
    calendar_days = (cycle_dates[-1] - cycle_dates[0]).days + 1

    gates = {
        "minimum_sessions": _gate(
            len(cycles) >= minimum_sessions, len(cycles), minimum_sessions
        ),
        "minimum_calendar_days": _gate(
            calendar_days >= minimum_calendar_days,
            calendar_days,
            minimum_calendar_days,
        ),
        "expected_session_continuity": _gate(session_continuity, session_continuity, True),
        "positive_excess_return": _gate(excess_return > 0, excess_return, "> 0"),
        "maximum_drawdown": _gate(
            observed_drawdown <= maximum_drawdown,
            observed_drawdown,
            f"<= {maximum_drawdown}",
        ),
        "walk_forward_excess": _gate(
            walk_forward_passed,
            walk_forward_excess,
            "every segment > 0",
        ),
        "daily_data_health": _gate(all_health_passed, all_health_passed, True),
        "reproducible_evidence": _gate(all_reproducible, all_reproducible, True),
        "execution_integrity": _gate(all_execution_valid, all_execution_valid, True),
        "approved_policy": _gate(all_policy_approved, all_policy_approved, True),
        "dqn_exposure_disabled": _gate(dqn_disabled, dqn_disabled, True),
        "live_trading_disabled": _gate(live_disabled, live_disabled, True),
    }
    duration_complete = (
        gates["minimum_sessions"]["passed"]
        and gates["minimum_calendar_days"]["passed"]
    )
    integrity_names = (
        "expected_session_continuity",
        "walk_forward_excess",
        "daily_data_health",
        "reproducible_evidence",
        "execution_integrity",
        "approved_policy",
        "dqn_exposure_disabled",
        "live_trading_disabled",
    )
    integrity_passed = all(bool(gates[name]["passed"]) for name in integrity_names)
    performance_passed = bool(
        gates["positive_excess_return"]["passed"]
        and gates["maximum_drawdown"]["passed"]
    )
    if duration_complete and not gates["positive_excess_return"]["passed"]:
        failures.append("completed window has no positive CSI 300 excess return")
    if duration_complete and not gates["maximum_drawdown"]["passed"]:
        failures.append("completed window exceeds the maximum drawdown limit")
    if not integrity_passed or (duration_complete and not performance_passed):
        status = "FAILED"
    elif duration_complete and performance_passed:
        status = "ELIGIBLE_FOR_REVIEW"
    else:
        status = "COLLECTING"

    return {
        "schema_version": 1,
        "kind": "csi300_paper_validation_report",
        "status": status,
        "live_trading_authorized": False,
        "anchor": file_reference(anchor),
        "latest_cycle": file_reference(cycles[-1][0]),
        "window": {
            "anchor_date": anchor_date.isoformat(),
            "first_counted_date": cycle_dates[0].isoformat(),
            "latest_counted_date": cycle_dates[-1].isoformat(),
            "calendar_days": calendar_days,
        },
        "metrics": {
            "valid_sessions": len(cycles),
            "paper_return": round(paper_return, 10),
            "benchmark_return": round(benchmark_return, 10),
            "excess_return": round(excess_return, 10),
            "maximum_drawdown": round(observed_drawdown, 10),
            "turnover": round(total_notional / anchor_equity, 10),
            "modeled_cost": round(total_cost, 6),
            "trade_count": trade_count,
            "constraint_blocks": dict(sorted(constraint_blocks.items())),
            "walk_forward_excess": walk_forward_excess,
        },
        "gates": gates,
        "failures": failures,
    }


def _load_v2_cycles(
    paths: Sequence[Path], *, anchor_date: date
) -> list[tuple[Path, dict[str, object], date]]:
    result: list[tuple[Path, dict[str, object], date]] = []
    for raw_path in paths:
        path = raw_path.resolve()
        payload = _load_json(path)
        if payload.get("schema_version") == 1:
            continue
        if payload.get("schema_version") != 2 or payload.get("kind") != "paper_trading_cycle":
            raise ValueError(f"unsupported paper cycle manifest: {path}")
        cycle_date = date.fromisoformat(str(payload.get("as_of", "")))
        if cycle_date <= anchor_date:
            continue
        result.append((path, payload, cycle_date))
    result.sort(key=lambda item: item[2])
    dates = [item[2] for item in result]
    if len(dates) != len(set(dates)):
        raise ValueError("paper cycle manifests contain duplicate dates")
    return result


def _audit_cycle(
    cycle_date: date,
    *,
    inputs: Mapping[str, Path],
    artifacts: Mapping[str, Path],
    account_after_sha256: str,
    maximum_position_weight: float,
) -> dict[str, object]:
    failures: list[str] = []
    reproducible = True
    execution_valid = True
    health_passed = True

    decision = _load_json(inputs["research_report"])
    health = _load_json(inputs["data_health"])
    report = _load_json(artifacts["paper_report"])
    if decision.get("as_of") != cycle_date.isoformat():
        failures.append(f"{cycle_date}: decision report date mismatch")
        reproducible = False
    decision_inputs = _mapping(decision.get("inputs"), "decision inputs")
    missing_decision_inputs = sorted(
        set(_REQUIRED_DECISION_INPUTS) - set(decision_inputs)
    )
    if missing_decision_inputs:
        raise ValueError(
            f"decision inputs are missing required references: {missing_decision_inputs}"
        )
    decision_paths: dict[str, Path] = {}
    for name, reference in decision_inputs.items():
        decision_paths[str(name)] = verify_file_reference(
            _mapping(reference, "decision input reference")
        )
    for name in (
        "factor_manifest",
        "signal_price_manifest",
        "execution_price_manifest",
        "corporate_action_manifest",
    ):
        load_verified_manifest(decision_paths[name], expected_layer="processed")
    for name in ("execution_prices", "corporate_actions", "benchmark"):
        if file_reference(decision_paths[name])["sha256"] != file_reference(inputs[name])[
            "sha256"
        ]:
            failures.append(f"{cycle_date}: decision and cycle {name} inputs differ")
            reproducible = False

    metrics = _mapping(health.get("metrics"), "data health metrics")
    health_passed = (
        health.get("passed") is True
        and decision.get("data_health_passed") is True
        and decision.get("data_health") == health
        and int(metrics.get("fundamental_stale_count", -1)) == 0
        and int(metrics.get("capital_flow_stale_count", -1)) == 0
        and int(metrics.get("future_leakage_count", -1)) == 0
    )
    if not health_passed:
        failures.append(f"{cycle_date}: data health or leakage checks failed")

    current_symbols = _universe_symbols(inputs["current_universe"])
    if len(current_symbols) != 300:
        failures.append(f"{cycle_date}: current CSI 300 universe does not contain 300 symbols")
        reproducible = False
    membership_symbols = set(
        active_symbols(load_membership_intervals(decision_paths["membership"]), cycle_date)
    )
    if current_symbols != membership_symbols:
        failures.append(f"{cycle_date}: current universe differs from historical membership")
        reproducible = False
    benchmark_dates = _benchmark_dates(
        inputs["benchmark"], after=None, through=cycle_date
    )
    if not benchmark_dates or benchmark_dates[-1] != cycle_date:
        failures.append(f"{cycle_date}: benchmark does not end on cycle date")
        reproducible = False

    account = _mapping(report.get("account"), "paper report account")
    if canonical_json_sha256(account) != account_after_sha256:
        raise ValueError(f"paper report account hash mismatch at {cycle_date}")
    nav = _mapping(report.get("nav"), "paper report NAV")
    nav_history = account.get("nav_history")
    if (
        account.get("last_processed_date") != cycle_date.isoformat()
        or nav.get("trade_date") != cycle_date.isoformat()
        or not isinstance(nav_history, list)
        or not nav_history
        or not isinstance(nav_history[-1], Mapping)
        or nav_history[-1].get("trade_date") != cycle_date.isoformat()
        or float(nav.get("equity", -1)) != float(nav_history[-1].get("equity", -2))
    ):
        failures.append(f"{cycle_date}: paper NAV and account reconciliation failed")
        reproducible = False
    equity = float(nav.get("equity", 0.0))
    if equity <= 0:
        failures.append(f"{cycle_date}: paper equity is not positive")
        reproducible = False

    bars = _execution_bars(inputs["execution_prices"], cycle_date)
    reconciled_equity = _account_equity(account, bars)
    if reconciled_equity is None or round(reconciled_equity, 6) != round(equity, 6):
        failures.append(f"{cycle_date}: full paper account equity reconciliation failed")
        reproducible = False

    targets = _target_weights(artifacts["targets"])
    pending = account.get("pending_targets")
    if not isinstance(pending, Mapping) or {
        str(symbol): float(weight) for symbol, weight in pending.items()
    } != targets:
        failures.append(f"{cycle_date}: queued targets do not match paper account")
        reproducible = False
    if any(weight < 0 or weight > maximum_position_weight for weight in targets.values()):
        failures.append(f"{cycle_date}: target weight exceeds approved position limit")
        reproducible = False

    trades = report.get("trades")
    blocked_orders = report.get("blocked_orders")
    corporate_actions = report.get("corporate_actions")
    if not isinstance(trades, list) or not isinstance(blocked_orders, list):
        raise ValueError("paper report trades and blocked orders must be lists")
    if not isinstance(corporate_actions, list):
        raise ValueError("paper report corporate actions must be a list")
    notional = 0.0
    cost = 0.0
    cost_model = AShareCostModel(
        commission_rate=0.0003,
        minimum_commission=5.0,
        include_stamp_duty=True,
    )
    for trade in trades:
        item = _mapping(trade, "paper trade")
        if item.get("trade_date") != cycle_date.isoformat():
            failures.append(f"{cycle_date}: trade date mismatch")
            reproducible = False
        notional += float(item.get("notional", 0.0))
        cost += float(item.get("total_cost", 0.0))
        symbol = str(item.get("symbol", ""))
        action = str(item.get("action", ""))
        bar = bars.get(symbol)
        if bar is None or action not in {"buy", "sell"}:
            failures.append(f"{cycle_date}: execution anomaly for trade {symbol}")
            execution_valid = False
        else:
            base_price = float(bar.get("execution_price", bar.get("open", bar["close"])))
            multiplier = 1.0005 if action == "buy" else 0.9995
            if float(item.get("price", 0.0)) != round(base_price * multiplier, 6):
                failures.append(f"{cycle_date}: execution anomaly for trade price {symbol}")
                execution_valid = False
        shares = int(item.get("shares", 0))
        trade_notional = float(item.get("notional", 0.0))
        if (
            shares <= 0
            or shares % 100 != 0
            or round(shares * float(item.get("price", 0.0)), 6)
            != round(trade_notional, 6)
        ):
            failures.append(f"{cycle_date}: execution anomaly for trade sizing {symbol}")
            execution_valid = False
        expected_cost = (
            cost_model.buy_cost(trade_notional, cycle_date)
            if action == "buy"
            else cost_model.sell_cost(trade_notional, cycle_date)
        )
        dividend_tax = float(item.get("dividend_tax", 0.0))
        if (
            float(item.get("commission", -1.0)) != expected_cost.commission
            or float(item.get("stamp_duty", -1.0)) != expected_cost.stamp_duty
            or float(item.get("total_cost", -1.0))
            != round(expected_cost.total + dividend_tax, 6)
        ):
            failures.append(f"{cycle_date}: execution anomaly for modeled costs {symbol}")
            execution_valid = False
    blocks: Counter[str] = Counter()
    for blocked in blocked_orders:
        item = _mapping(blocked, "blocked paper order")
        reason = str(item.get("reason", ""))
        if reason not in _ALLOWED_BLOCK_REASONS:
            failures.append(f"{cycle_date}: execution anomaly for blocked reason {reason}")
            execution_valid = False
        else:
            blocks[reason] += 1
    input_action_keys = _corporate_action_keys(inputs["corporate_actions"])
    for action in corporate_actions:
        item = _mapping(action, "paper corporate action")
        if item.get("ex_date") != cycle_date.isoformat():
            failures.append(f"{cycle_date}: corporate-action date mismatch")
            reproducible = False
        if _corporate_action_key(item) not in input_action_keys:
            failures.append(f"{cycle_date}: corporate action is absent from the input ledger")
            reproducible = False

    return {
        "failures": failures,
        "health_passed": health_passed,
        "reproducible": reproducible,
        "execution_valid": execution_valid,
        "equity": equity,
        "notional": notional,
        "cost": cost,
        "trade_count": len(trades),
        "constraint_blocks": blocks,
    }


def _verified_references(
    payload: Mapping[str, object], section: str, required: Sequence[str]
) -> dict[str, Path]:
    values = _mapping(payload.get(section), f"cycle {section}")
    result: dict[str, Path] = {}
    for name, reference in values.items():
        if not isinstance(reference, Mapping):
            raise ValueError(f"cycle {section} {name} reference must be an object")
        result[str(name)] = verify_file_reference(reference)
    missing = sorted(set(required) - set(result))
    if missing:
        raise ValueError(f"cycle {section} is missing required references: {missing}")
    return result


def _latest_input_path(payload: Mapping[str, object], name: str) -> Path:
    inputs = _mapping(payload.get("inputs"), "cycle inputs")
    reference = _mapping(inputs.get(name), f"cycle {name} input")
    return verify_file_reference(reference)


def _walk_forward_excess(anchor_artifacts: Mapping[str, object]) -> list[float]:
    reference = _mapping(anchor_artifacts.get("comparison"), "anchor comparison")
    comparison = _load_json(verify_file_reference(reference))
    segments = comparison.get("walk_forward")
    if not isinstance(segments, list):
        return []
    result: list[float] = []
    for segment in segments:
        if not isinstance(segment, Mapping):
            return []
        raw_value = segment.get("candidate_benchmark_excess_return")
        if raw_value is None:
            raw_value = segment.get("excess_return")
        if raw_value is None:
            return []
        result.append(float(raw_value))
    return result


def _benchmark_dates(path: Path, *, after: date | None, through: date) -> list[date]:
    values = _benchmark_values(path)
    return [
        trade_date
        for trade_date in sorted(values)
        if (after is None or trade_date > after) and trade_date <= through
    ]


def _benchmark_endpoints(path: Path, *, start: date, end: date) -> tuple[float, float]:
    values = _benchmark_values(path)
    if start not in values or end not in values:
        raise ValueError("benchmark is missing validation return endpoints")
    if values[start] <= 0 or values[end] <= 0:
        raise ValueError("benchmark endpoint values must be positive")
    return values[start], values[end]


def _benchmark_values(path: Path) -> dict[date, float]:
    result: dict[date, float] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            raw_date = row.get("trade_date")
            raw_close = row.get("index_close") or row.get("close")
            if raw_date and raw_close not in {None, ""}:
                result[date.fromisoformat(str(raw_date))] = float(raw_close)
    if not result:
        raise ValueError("benchmark contains no dated close values")
    return result


def _universe_symbols(path: Path) -> set[str]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            str(row.get("symbol", "")).strip()
            for row in csv.DictReader(handle)
            if str(row.get("symbol", "")).strip()
        }


def _target_weights(path: Path) -> dict[str, float]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            str(row["symbol"]): float(row["raw_target_weight"])
            for row in csv.DictReader(handle)
            if row.get("symbol")
        }


def _execution_bars(
    path: Path, cycle_date: date
) -> dict[str, dict[str, object]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            str(row["symbol"]): dict(row)
            for row in csv.DictReader(handle)
            if row.get("trade_date") == cycle_date.isoformat()
        }


def _account_equity(
    account: Mapping[str, object], bars: Mapping[str, Mapping[str, object]]
) -> float | None:
    positions = account.get("positions")
    if not isinstance(positions, Mapping):
        return None
    result = float(account.get("cash", 0.0))
    for symbol, raw_position in positions.items():
        if not isinstance(raw_position, Mapping) or str(symbol) not in bars:
            return None
        result += int(raw_position.get("shares", 0)) * float(bars[str(symbol)]["close"])
    return result


def _corporate_action_keys(path: Path) -> set[tuple[str, str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {_corporate_action_key(row) for row in csv.DictReader(handle)}


def _corporate_action_key(value: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(value.get("symbol", "")),
        str(value.get("ex_date", "")),
        str(value.get("action_type", "distribution")),
    )


def _maximum_drawdown(equities: Sequence[float]) -> float:
    peak = equities[0]
    result = 0.0
    for equity in equities:
        peak = max(peak, equity)
        result = max(result, (peak - equity) / peak if peak else 0.0)
    return result


def _gate(passed: bool, observed: object, required: object) -> dict[str, object]:
    return {"passed": passed, "observed": observed, "required": required}


def _empty_report(
    *,
    anchor: Path,
    anchor_date: date,
    anchor_equity: float,
    walk_forward_excess: list[float],
    walk_forward_passed: bool,
    minimum_sessions: int,
    minimum_calendar_days: int,
    maximum_drawdown: float,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "csi300_paper_validation_report",
        "status": "NO_EVIDENCE",
        "live_trading_authorized": False,
        "anchor": file_reference(anchor),
        "latest_cycle": None,
        "window": {
            "anchor_date": anchor_date.isoformat(),
            "first_counted_date": None,
            "latest_counted_date": None,
            "calendar_days": 0,
        },
        "metrics": {
            "valid_sessions": 0,
            "paper_return": 0.0,
            "benchmark_return": 0.0,
            "excess_return": 0.0,
            "maximum_drawdown": 0.0,
            "turnover": 0.0,
            "modeled_cost": 0.0,
            "trade_count": 0,
            "constraint_blocks": {},
            "walk_forward_excess": walk_forward_excess,
            "anchor_equity": anchor_equity,
        },
        "gates": {
            "minimum_sessions": _gate(False, 0, minimum_sessions),
            "minimum_calendar_days": _gate(False, 0, minimum_calendar_days),
            "expected_session_continuity": _gate(True, True, True),
            "positive_excess_return": _gate(False, 0.0, "> 0"),
            "maximum_drawdown": _gate(True, 0.0, f"<= {maximum_drawdown}"),
            "walk_forward_excess": _gate(
                walk_forward_passed, walk_forward_excess, "every segment > 0"
            ),
            "daily_data_health": _gate(True, True, True),
            "reproducible_evidence": _gate(True, True, True),
            "execution_integrity": _gate(True, True, True),
            "approved_policy": _gate(True, True, True),
            "dqn_exposure_disabled": _gate(True, True, True),
            "live_trading_disabled": _gate(True, True, True),
        },
        "failures": [],
    }


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload
