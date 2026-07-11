from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_collect_historical_prices_writes_immutable_symbol_artifacts(tmp_path: Path) -> None:
    membership = tmp_path / "membership.csv"
    membership.write_text(
        "index_code,symbol,member_from,member_to,source,source_fetched_at\n"
        "000300,000001.SZ,2021-01-01,,csindex,2026-07-11T00:00:00+08:00\n"
        "000300,600000.SH,2021-01-01,,csindex,2026-07-11T00:00:00+08:00\n",
        encoding="utf-8",
    )
    fixture = tmp_path / "prices.json"
    fixture.write_text(
        json.dumps(
            {
                "000001.SZ": [_bar("000001.SZ", "2026-01-02", 10.0)],
                "600000.SH": [_bar("600000.SH", "2026-01-02", 8.0)],
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/collect_historical_prices.py",
            "--source",
            "fixture",
            "--fixture-input",
            str(fixture),
            "--membership",
            str(membership),
            "--start",
            "2026-01-01",
            "--end",
            "2026-01-03",
            "--run-id",
            "prices-1",
            "--raw-root",
            str(tmp_path / "raw"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    manifest = json.loads((tmp_path / "raw/prices-1/manifest.json").read_text(encoding="utf-8"))
    assert manifest["request"]["membership"] == str(membership.resolve())
    assert manifest["request"]["adjust"] == "qfq"
    assert len(manifest["request"]["membership_sha256"]) == 64
    assert {artifact["path"] for artifact in manifest["artifacts"]} == {
        "prices/000001.SZ.jsonl",
        "prices/600000.SH.jsonl",
    }
    assert all(scope["status"] == "success" for scope in manifest["scopes"])


def test_collect_historical_prices_resumes_completed_symbols_and_retries_failures(
    tmp_path: Path,
) -> None:
    membership = tmp_path / "membership.csv"
    membership.write_text(
        "symbol\n000001.SZ\n600000.SH\n",
        encoding="utf-8",
    )
    first_fixture = tmp_path / "first.json"
    first_fixture.write_text(
        json.dumps(
            {
                "000001.SZ": [_bar("000001.SZ", "2026-01-02", 10.0)],
                "600000.SH": {"error": "temporary failure"},
            }
        ),
        encoding="utf-8",
    )
    first = _run_collect(tmp_path, membership, first_fixture, "prices-1")
    assert first.returncode == 2

    second_fixture = tmp_path / "second.json"
    second_fixture.write_text(
        json.dumps(
            {
                "000001.SZ": {"error": "must be reused"},
                "600000.SH": [_bar("600000.SH", "2026-01-02", 8.0)],
            }
        ),
        encoding="utf-8",
    )
    second = _run_collect(
        tmp_path,
        membership,
        second_fixture,
        "prices-2",
        resume_from=tmp_path / "raw/prices-1/manifest.json",
    )

    assert second.returncode == 0, second.stderr
    manifest = json.loads((tmp_path / "raw/prices-2/manifest.json").read_text(encoding="utf-8"))
    status_by_symbol = {scope["symbol"]: scope["status"] for scope in manifest["scopes"]}
    assert status_by_symbol == {"000001.SZ": "reused", "600000.SH": "success"}


def test_collect_historical_prices_rejects_parallel_sina_runtime(tmp_path: Path) -> None:
    membership = tmp_path / "membership.csv"
    membership.write_text("symbol\n000001.SZ\n", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/collect_historical_prices.py",
            "--source",
            "akshare-sina",
            "--membership",
            str(membership),
            "--start",
            "2026-01-01",
            "--end",
            "2026-01-03",
            "--run-id",
            "prices-1",
            "--raw-root",
            str(tmp_path / "raw"),
            "--workers",
            "2",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "akshare-sina requires --workers 1" in completed.stderr


def _run_collect(
    root: Path,
    membership: Path,
    fixture: Path,
    run_id: str,
    *,
    resume_from: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "scripts/collect_historical_prices.py",
        "--source",
        "fixture",
        "--fixture-input",
        str(fixture),
        "--membership",
        str(membership),
        "--start",
        "2026-01-01",
        "--end",
        "2026-01-03",
        "--run-id",
        run_id,
        "--raw-root",
        str(root / "raw"),
    ]
    if resume_from is not None:
        command.extend(("--resume-from", str(resume_from)))
    return subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )


def _bar(symbol: str, trade_date: str, close: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 100.0,
        "amount": close * 100.0,
        "source": "fixture",
    }
