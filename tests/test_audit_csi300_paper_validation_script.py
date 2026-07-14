from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from test_paper_validation import _load_json, _write_json, _write_passing_series


ROOT = Path(__file__).resolve().parents[1]


def test_audit_cli_discovers_cycles_and_writes_collecting_report(tmp_path: Path) -> None:
    anchor, _ = _write_passing_series(tmp_path, sessions=2, span_days=2)
    output = tmp_path / "validation_report.json"

    completed = _run(anchor, tmp_path / "cycles", output)

    assert completed.returncode == 0, completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "COLLECTING"
    assert report["metrics"]["valid_sessions"] == 2
    assert "live_trading_enabled=false" in completed.stdout


def test_audit_cli_returns_nonzero_for_broken_chain(tmp_path: Path) -> None:
    anchor, cycles = _write_passing_series(tmp_path, sessions=2, span_days=2)
    payload = _load_json(cycles[1])
    payload["account_before_sha256"] = "wrong"
    _write_json(cycles[1], payload)
    output = tmp_path / "validation_report.json"

    completed = _run(anchor, tmp_path / "cycles", output)

    assert completed.returncode != 0
    assert "account hash chain" in completed.stderr
    assert not output.exists()


def _run(anchor: Path, cycle_root: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/audit_csi300_paper_validation.py",
            "--anchor",
            str(anchor),
            "--cycle-root",
            str(cycle_root),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
