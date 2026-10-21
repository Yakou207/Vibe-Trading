from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from fintech_quant.reports.desk import (
    build_desk_snapshot,
    latest_complete_cycle,
    render_desk_html,
    watched_symbols,
)


ROOT = Path(__file__).resolve().parents[1]
SESSIONS = ("2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16")


def test_snapshot_reads_latest_complete_cycle_without_mutating_it(tmp_path: Path) -> None:
    cycles = _write_cycles(tmp_path)
    before = _tree_hashes(cycles)

    snapshot = build_desk_snapshot(cycles)

    assert _tree_hashes(cycles) == before
    assert snapshot["as_of"] == "2026-07-16"
    assert snapshot["mode"] == "post_close"
    assert snapshot["header"]["valid_sessions"] == 2
    assert snapshot["header"]["live_trading_authorized"] is False
    assert latest_complete_cycle(cycles).name == "2026-07-16"


def test_funnel_counts_follow_policy_gates_and_risk_veto(tmp_path: Path) -> None:
    snapshot = build_desk_snapshot(_write_cycles(tmp_path))

    counts = {row["stage"]: row["count"] for row in snapshot["funnel"]}
    assert counts == {
        "members": 3,
        "data_gate": 3,
        "score_gate": 2,
        "confidence_gate": 2,
        "risk_veto": 1,
        "targets": 1,
    }
    vetoed = {row["symbol"]: row["vetoed"] for row in snapshot["candidates"]}
    assert vetoed == {"600001.SH": False, "600002.SH": True, "600003.SH": False}
    vet = next(agent for agent in snapshot["agents"] if agent["id"] == "VET")
    assert vet["status"] == "alert"


def test_failed_data_health_blocks_crawler_and_empties_funnel(tmp_path: Path) -> None:
    cycles = _write_cycles(tmp_path, health_passed=False)

    snapshot = build_desk_snapshot(cycles)

    crawler = next(agent for agent in snapshot["agents"] if agent["id"] == "CRAWLER")
    assert crawler["status"] == "blocked"
    assert {row["stage"]: row["count"] for row in snapshot["funnel"]}["data_gate"] == 0


def test_timeline_marks_complete_partial_and_missing_sessions(tmp_path: Path) -> None:
    snapshot = build_desk_snapshot(_write_cycles(tmp_path))

    assert snapshot["timeline"] == [
        {"date": "2026-07-14", "status": "missing"},
        {"date": "2026-07-15", "status": "partial"},
        {"date": "2026-07-16", "status": "complete"},
    ]


def test_paper_curve_starts_at_audit_anchor(tmp_path: Path) -> None:
    snapshot = build_desk_snapshot(_write_cycles(tmp_path))

    curve = snapshot["paper_curve"]
    assert curve["dates"] == ["2026-07-13", "2026-07-16"]
    assert curve["csi300"] == [100000.0, 102000.0]


def test_live_quotes_mark_positions_and_targets(tmp_path: Path) -> None:
    cycles = _write_cycles(tmp_path)
    quotes = [
        {"symbol": "600001.SH", "price": "11.0", "change_pct": "1.5"},
        {"symbol": "600009.SH", "price": "21.0", "change_pct": "-2.0"},
    ]

    snapshot = build_desk_snapshot(cycles, quotes=quotes)

    assert snapshot["mode"] == "intraday"
    position = snapshot["positions"][0]
    assert position["mark_source"] == "live_quote"
    assert position["market_value"] == 2100.0
    assert position["unrealized_pnl"] == 100.0
    assert snapshot["header"]["live_equity"] == 98100.0
    assert snapshot["targets"][0]["quote"] == {"price": 11.0, "change_pct": 1.5}
    assert "600009.SH" in watched_symbols(snapshot)


def test_rendered_html_escapes_embedded_snapshot(tmp_path: Path) -> None:
    cycles = _write_cycles(tmp_path, name="</script><b>x")
    html_text = render_desk_html(build_desk_snapshot(cycles), live=False)

    assert "</script><b>x" not in html_text
    assert "const LIVE = false;" in html_text
    assert "__DESK_" not in html_text


def test_latest_complete_cycle_requires_complete_directory(tmp_path: Path) -> None:
    cycles = tmp_path / "cycles"
    (cycles / "2026-07-15").mkdir(parents=True)

    with pytest.raises(FileNotFoundError):
        latest_complete_cycle(cycles)


def test_export_script_writes_static_dashboard(tmp_path: Path) -> None:
    cycles = _write_cycles(tmp_path)
    output = tmp_path / "desk.html"

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "serve_trading_desk.py"),
            "--cycle-root",
            str(cycles),
            "--export",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert f"output={output}" in result.stdout
    assert "2026-07-16" in output.read_text(encoding="utf-8")


def test_server_streams_snapshot_events(tmp_path: Path) -> None:
    cycles = _write_cycles(tmp_path)
    port = _free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "scripts" / "serve_trading_desk.py"),
            "--cycle-root",
            str(cycles),
            "--port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        snapshot = json.loads(_get(f"http://127.0.0.1:{port}/api/snapshot"))
        assert snapshot["as_of"] == "2026-07-16"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/stream", timeout=5) as stream:
            assert stream.readline() == b"event: snapshot\n"
            payload = json.loads(stream.readline().decode("utf-8").removeprefix("data: "))
        assert payload["as_of"] == "2026-07-16"
    finally:
        process.terminate()
        process.wait(timeout=5)


def _get(url: str) -> str:
    deadline = time.monotonic() + 10
    while True:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.read().decode("utf-8")
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.1)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _write_cycles(tmp_path: Path, *, health_passed: bool = True, name: str = "甲") -> Path:
    cycles = tmp_path / "cycles"
    (cycles / "2026-07-15").mkdir(parents=True)
    (cycles / "2026-07-15" / "csi300_market_state.csv").write_text(
        "trade_date,index_close\n", encoding="utf-8"
    )
    _write_complete_cycle(cycles / "2026-07-13", as_of="2026-07-13", health_passed=True, name=name)
    _write_complete_cycle(
        cycles / "2026-07-16", as_of="2026-07-16", health_passed=health_passed, name=name
    )
    return cycles


def _write_complete_cycle(path: Path, *, as_of: str, health_passed: bool, name: str) -> None:
    path.mkdir(parents=True)
    policy = {
        "buy_threshold": 70.0,
        "minimum_score_confidence": 0.8,
        "maximum_position_weight": 0.08,
        "drawdown_reduce": 0.08,
        "drawdown_liquidate": 0.09,
        "drawdown_validation_limit": 0.1,
        "dqn_exposure_enabled": False,
        "live_trading_enabled": False,
        "strategy": "scored_multi_factor_baseline",
    }
    _write_json(
        path / "cycle_manifest.json",
        {
            "as_of": as_of,
            "git_sha": "abc1234def",
            "policy": policy,
            "evidence_parent": {"sha256": "parent"},
        },
    )
    scores = [
        _score("600001.SH", 78.5, 0.8125),
        _score("600002.SH", 72.0, 0.8125),
        _score("600003.SH", 50.0, 0.5),
    ]
    _write_json(
        path / "decision_report.json",
        {
            "as_of": as_of,
            "active_member_count": 3,
            "data_health_passed": health_passed,
            "data_health": {
                "passed": health_passed,
                "metrics": {"price_coverage": 0.99, "fundamental_coverage": 1.0},
            },
            "scores": scores,
            "risk_limits": {"max_position_weight": 0.08},
            "risk_summary": {"total_warnings": 1, "by_rule": {"main_outflow": 1}},
            "risk_warnings": [{"symbol": "600002.SH", "rule": "main_outflow", "action": "reduce"}],
        },
    )
    _write_json(
        path / "paper_report.json",
        {
            "account": {
                "cash": 96000.0,
                "positions": {
                    "600009.SH": {"shares": 100, "cost_basis": 20.0, "last_buy_date": "2026-07-14"}
                },
                "drawdown_control_state": {
                    "actual_peak": 100000.0,
                    "regime": "normal",
                    "transitions": [],
                },
                "pending_signal_date": as_of,
                "nav_history": [
                    {"trade_date": "2026-06-30", "equity": 100000.0},
                    {"trade_date": "2026-07-13", "equity": 100000.0},
                    {"trade_date": "2026-07-16", "equity": 98000.0},
                ],
                "shadow_nav_history": [{"trade_date": "2026-07-16", "equity": 98000.0}],
            },
            "nav": {"equity": 98000.0, "exposure_multiplier": 1.0},
            "trades": [],
            "blocked_orders": [],
        },
    )
    _write_json(
        path / "validation_report.json",
        {
            "status": "FAILED",
            "live_trading_authorized": False,
            "failures": ["missing expected CSI 300 sessions"],
            "gates": {"minimum_sessions": {"observed": 2, "passed": False, "required": 40}},
            "metrics": {"valid_sessions": 2, "paper_return": -0.02, "benchmark_return": 0.02},
            "window": {"anchor_date": "2026-07-13", "calendar_days": 3},
        },
    )
    closes = {
        "2026-06-30": 900.0,
        "2026-07-13": 1000.0,
        "2026-07-14": 1010.0,
        "2026-07-15": 1015.0,
        "2026-07-16": 1020.0,
    }
    (path / "csi300_market_state.csv").write_text(
        "trade_date,index_symbol,index_close\n"
        + "".join(f"{day},sh000300,{close}\n" for day, close in closes.items() if day <= as_of),
        encoding="utf-8",
    )
    (path / "current_universe.csv").write_text(
        f"symbol,name\n600001.SH,{name}\n600002.SH,乙\n600003.SH,丙\n600009.SH,丁\n",
        encoding="utf-8",
    )
    (path / "targets.csv").write_text(
        "symbol,raw_target_weight,target_weight,portfolio_exposure_multiplier,score,score_confidence,rl_action,reason\n"
        "600001.SH,0.08,0.08,1.0,78.5,0.8125,buy,score=78.50\n",
        encoding="utf-8",
    )


def _score(symbol: str, total: float, confidence: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "total": total,
        "confidence": confidence,
        "components": {
            "fundamental": {"score": 35.0, "max_score": 35.0, "reasons": ["ROE is above 12%."]}
        },
    }


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_desk_defaults_resolve_from_project_root_not_cwd(tmp_path, monkeypatch) -> None:
    from scripts.serve_trading_desk import ROOT as SCRIPT_ROOT, build_parser

    monkeypatch.chdir(tmp_path)
    args = build_parser().parse_args([])

    for name in (
        "cycle_root", "pnl_curve", "state", "pool_root", "pool_v2_root",
        "scoring_v2", "intel_cache", "jev_records",
    ):
        path = getattr(args, name)
        assert path.is_absolute() and path.is_relative_to(SCRIPT_ROOT), name
    assert args.scoring_v2 == SCRIPT_ROOT / "outputs/research/scoring_v2/latest_scores.json"
