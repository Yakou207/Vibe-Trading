from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch


def test_collect_point_in_time_factors_writes_versioned_raw_run(tmp_path: Path) -> None:
    membership_path = _write_membership(tmp_path)
    fixture_path = _write_fixture(tmp_path / "fixture.json", fail_scope=None)
    raw_root = tmp_path / "raw-runs"

    completed = _run_collector(
        membership_path,
        fixture_path,
        raw_root,
        run_id="raw-1",
    )

    assert completed.returncode == 0, completed.stderr
    manifest_path = raw_root / "raw-1/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["request"]["symbols"] == ["000001.SZ", "600000.SH"]
    assert len(manifest["request"]["membership_sha256"]) == 64
    assert len(manifest["artifacts"]) == 6
    assert {scope["status"] for scope in manifest["scopes"]} == {"success"}
    state = json.loads((raw_root / "raw-1/collection_state.json").read_text(encoding="utf-8"))
    assert state["completed_scopes"] == 6
    assert state["failed_scopes"] == 0
    assert "fetched_scopes=6" in completed.stdout
    assert "failed_scopes=0" in completed.stdout


def test_collect_point_in_time_factors_resume_reuses_success_and_retries_failure(
    tmp_path: Path,
) -> None:
    membership_path = _write_membership(tmp_path)
    failing_fixture = _write_fixture(
        tmp_path / "failing.json",
        fail_scope=("600000.SH", "capital_flow"),
    )
    healthy_fixture = _write_fixture(tmp_path / "healthy.json", fail_scope=None)
    raw_root = tmp_path / "raw-runs"

    first = _run_collector(
        membership_path,
        failing_fixture,
        raw_root,
        run_id="raw-1",
    )
    second = _run_collector(
        membership_path,
        healthy_fixture,
        raw_root,
        run_id="raw-2",
        resume_from=raw_root / "raw-1/manifest.json",
    )

    assert first.returncode == 2
    assert second.returncode == 0, second.stderr
    manifest = json.loads((raw_root / "raw-2/manifest.json").read_text(encoding="utf-8"))
    assert manifest["parent_manifest"] == str(raw_root / "raw-1/manifest.json")
    assert {scope["status"] for scope in manifest["scopes"]} == {"success", "reused"}
    assert "reused_scopes=5" in second.stdout
    assert "fetched_scopes=1" in second.stdout
    assert len(manifest["artifacts"]) == 6


def test_collect_point_in_time_factors_appends_new_scopes_without_reusing_parent(
    tmp_path: Path,
) -> None:
    membership_path = _write_membership(tmp_path)
    first_fixture = _write_fixture(tmp_path / "first.json", fail_scope=None)
    child_fixture = _write_fixture(tmp_path / "child.json", fail_scope=None)
    raw_root = tmp_path / "raw-runs"
    first = _run_collector(
        membership_path,
        first_fixture,
        raw_root,
        run_id="raw-1",
    )
    assert first.returncode == 0, first.stderr
    parent_manifest = raw_root / "raw-1/manifest.json"

    child = _run_collector(
        membership_path,
        child_fixture,
        raw_root,
        run_id="raw-2",
        append_from=parent_manifest,
        start="2026-07-01",
        end="2026-07-01",
    )

    assert child.returncode == 0, child.stderr
    manifest = json.loads((raw_root / "raw-2/manifest.json").read_text(encoding="utf-8"))
    assert manifest["parent_manifest"] == str(parent_manifest.resolve())
    assert manifest["request"]["start"] == "2026-07-01"
    assert {scope["status"] for scope in manifest["scopes"]} == {"success"}
    assert "fetched_scopes=6" in child.stdout
    assert "reused_scopes=0" in child.stdout


def test_real_fundamental_collection_uses_requested_end_as_snapshot_date() -> None:
    from scripts.collect_point_in_time_factors import _fetch_rows

    requested_end = date(2026, 6, 16)

    class FakeFetcher:
        def __init__(self, *, as_of: date) -> None:
            assert as_of == requested_end

        def fetch(self, symbol: str, sector: object, start: date, end: date) -> list[object]:
            return []

    with patch("scripts.collect_point_in_time_factors.AkShareFundamentalFetcher", FakeFetcher):
        rows = _fetch_rows(
            "akshare",
            None,
            "000001.SZ",
            "fundamentals",
            date(2021, 1, 1),
            requested_end,
        )

    assert rows == []


def test_collector_can_limit_groups_when_capital_flow_uses_explicit_proxy(tmp_path: Path) -> None:
    membership_path = _write_membership(tmp_path)
    fixture_path = _write_fixture(tmp_path / "fixture.json", fail_scope=None)
    raw_root = tmp_path / "raw-runs"

    completed = _run_collector(
        membership_path,
        fixture_path,
        raw_root,
        run_id="raw-1",
        groups=("fundamentals", "financial_statements"),
    )

    assert completed.returncode == 0, completed.stderr
    manifest = json.loads((raw_root / "raw-1/manifest.json").read_text(encoding="utf-8"))
    assert manifest["request"]["groups"] == ["fundamentals", "financial_statements"]
    assert len(manifest["artifacts"]) == 4
    assert not any(artifact["path"].startswith("capital_flow/") for artifact in manifest["artifacts"])


def test_collector_rejects_tampered_resume_artifact(tmp_path: Path) -> None:
    membership_path = _write_membership(tmp_path)
    fixture_path = _write_fixture(tmp_path / "fixture.json", fail_scope=None)
    raw_root = tmp_path / "raw-runs"
    first = _run_collector(membership_path, fixture_path, raw_root, run_id="raw-1")
    assert first.returncode == 0
    (raw_root / "raw-1/fundamentals/000001.SZ.jsonl").write_text("tampered\n", encoding="utf-8")

    second = _run_collector(
        membership_path,
        fixture_path,
        raw_root,
        run_id="raw-2",
        resume_from=raw_root / "raw-1/manifest.json",
    )

    assert second.returncode != 0
    assert "resume artifact hash mismatch" in second.stderr


def test_statement_lookback_catches_late_published_rows_and_dates_them_when_observed(
    tmp_path: Path,
) -> None:
    """Sina dates an evening report to that day, after the post-close fetch already ran."""
    from fintech_quant.data.factor_store import materialize_fundamentals
    from fintech_quant.information import InformationRepository

    membership_path = _write_membership(tmp_path)
    raw_root = tmp_path / "raw-runs"
    symbol = "000001.SZ"
    h1 = [_statement(symbol, kind, "2026-06-30", "2026-08-27") for kind in ("balance", "income")]
    q3_cash = _statement(symbol, "cash", "2026-09-30", "2026-10-29")
    parent_fixture = tmp_path / "parent.json"
    parent_fixture.write_text(json.dumps({symbol: {"financial_statements": [*h1, q3_cash]}}),
                              encoding="utf-8")
    parent = _run_collector(membership_path, parent_fixture, raw_root, run_id="raw-1",
                            groups=("financial_statements",), start="2026-08-01",
                            end="2026-10-29", extra=("--symbols", symbol))
    assert parent.returncode == 0, parent.stderr

    # What Sina returns a day later: the Q3 balance sheet and income statement are now there,
    # dated 10-29, plus an old Q1 row the chain never held.
    q3 = [_statement(symbol, kind, "2026-09-30", "2026-10-29") for kind in ("balance", "income")]
    q1 = _statement(symbol, "income", "2026-03-31", "2026-04-29")
    child_fixture = tmp_path / "child.json"
    child_fixture.write_text(
        json.dumps({symbol: {"financial_statements": [*h1, *q3, q3_cash, q1]}}), encoding="utf-8")
    child = _run_collector(membership_path, child_fixture, raw_root, run_id="raw-2",
                           append_from=raw_root / "raw-1/manifest.json",
                           groups=("financial_statements",), start="2026-10-30",
                           end="2026-10-30",
                           extra=("--symbols", symbol, "--statement-lookback-days", "92"))

    assert child.returncode == 0, child.stderr
    manifest = json.loads((raw_root / "raw-2/manifest.json").read_text(encoding="utf-8"))
    assert manifest["request"]["statement_lookback_days"] == 92
    rows = [json.loads(line) for line in
            (raw_root / f"raw-2/financial_statements/{symbol}.jsonl").read_text().splitlines()]
    assert sorted(row["title"] for row in rows) == [
        f"{symbol} balance 2026-09-30", f"{symbol} income 2026-09-30"]
    for row in rows:
        assert row["published_at"] == "2026-10-30"
        assert row["metadata"]["provider_published_at"] == "2026-10-29"
        assert row["metadata"]["available_date_source"] == "first_observed"

    records = [record for run in ("raw-1", "raw-2") for record in
               InformationRepository(raw_root / f"{run}/financial_statements/{symbol}.jsonl")
               .all_records()]
    snapshots = {s.available_date.isoformat(): s for s in
                 materialize_fundamentals(records, source_fetched_at="fixture")}
    assert snapshots["2026-10-30"].report_period == date(2026, 9, 30)
    assert snapshots["2026-10-30"].values["roe"] is not None

    # The next day sees the same rows again and adds nothing.
    again = _run_collector(membership_path, child_fixture, raw_root, run_id="raw-3",
                           append_from=raw_root / "raw-2/manifest.json",
                           groups=("financial_statements",), start="2026-10-31",
                           end="2026-10-31",
                           extra=("--symbols", symbol, "--statement-lookback-days", "92"))
    assert again.returncode == 0, again.stderr
    assert (raw_root / f"raw-3/financial_statements/{symbol}.jsonl").read_text() == ""


def test_statement_lookback_catches_an_in_place_correction_and_reads_it_first(
    tmp_path: Path,
) -> None:
    from fintech_quant.data.factor_store import materialize_fundamentals
    from fintech_quant.information import InformationRepository

    membership_path = _write_membership(tmp_path)
    raw_root = tmp_path / "raw-runs"
    symbol = "000001.SZ"
    zero = _statement(symbol, "balance", "2026-09-30", "2026-10-27",
                      summary="total_assets=0.0; total_liabilities=0.0")
    income = _statement(symbol, "income", "2026-09-30", "2026-10-27")
    parent_fixture = tmp_path / "parent.json"
    parent_fixture.write_text(json.dumps({symbol: {"financial_statements": [zero, income]}}),
                              encoding="utf-8")
    parent = _run_collector(membership_path, parent_fixture, raw_root, run_id="raw-1",
                            groups=("financial_statements",), start="2026-10-01",
                            end="2026-10-27", extra=("--symbols", symbol))
    assert parent.returncode == 0, parent.stderr
    corrected = _statement(symbol, "balance", "2026-09-30", "2026-10-27")
    child_fixture = tmp_path / "child.json"
    child_fixture.write_text(json.dumps({symbol: {"financial_statements": [corrected, income]}}),
                             encoding="utf-8")
    child = _run_collector(membership_path, child_fixture, raw_root, run_id="raw-2",
                           append_from=raw_root / "raw-1/manifest.json",
                           groups=("financial_statements",), start="2026-11-05",
                           end="2026-11-05",
                           extra=("--symbols", symbol, "--statement-lookback-days", "92"))

    assert child.returncode == 0, child.stderr
    records = [record for run in ("raw-1", "raw-2") for record in
               InformationRepository(raw_root / f"{run}/financial_statements/{symbol}.jsonl")
               .all_records()]
    snapshots = {s.available_date.isoformat(): s for s in
                 materialize_fundamentals(records, source_fetched_at="fixture")}
    # The period counts from the corrected row: 15 * 4/3 earnings over 200 equity.
    assert list(snapshots) == ["2026-11-05"]
    assert snapshots["2026-11-05"].values["roe"] == 0.1


def _statement(symbol: str, kind: str, period: str, published_at: str,
               summary: str | None = None) -> dict[str, object]:
    summary = summary or {"balance": "total_assets=300.0; total_liabilities=100.0",
                          "income": "revenue=80.0; net_profit=15.0",
                          "cash": "operating_cash_flow=10.0"}[kind]
    return {
        "symbol": symbol,
        "sector": None,
        "published_at": published_at,
        "source": "akshare_financial_statement",
        "category": "stock_data",
        "title": f"{symbol} {kind} {period}",
        "url": "",
        "summary": summary,
        "risk_tags": ["selected_universe", "financial_statement"],
        "metadata": {"statement_type": kind, "report_period": period,
                     "available_date_source": "更新日期"},
    }


def _run_collector(
    membership_path: Path,
    fixture_path: Path,
    raw_root: Path,
    *,
    run_id: str,
    resume_from: Path | None = None,
    append_from: Path | None = None,
    groups: tuple[str, ...] | None = None,
    start: str = "2026-01-01",
    end: str = "2026-06-30",
    extra: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "scripts/collect_point_in_time_factors.py",
        "--source",
        "fixture",
        "--fixture-input",
        str(fixture_path),
        "--membership",
        str(membership_path),
        "--start",
        start,
        "--end",
        end,
        "--run-id",
        run_id,
        "--raw-root",
        str(raw_root),
        "--created-at",
        "2026-07-10T12:00:00+08:00",
    ]
    if resume_from is not None:
        command.extend(["--resume-from", str(resume_from)])
    if append_from is not None:
        command.extend(["--append-from", str(append_from)])
    if groups is not None:
        command.extend(["--groups", *groups])
    command.extend(extra)
    return subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )


def _write_membership(root: Path) -> Path:
    path = root / "membership.csv"
    path.write_text(
        "index_code,symbol,member_from,member_to,source,source_fetched_at\n"
        "000300,000001.SZ,2026-01-01,,csindex,2026-07-10T12:00:00+08:00\n"
        "000300,600000.SH,2026-01-01,,csindex,2026-07-10T12:00:00+08:00\n",
        encoding="utf-8",
    )
    return path


def _write_fixture(path: Path, fail_scope: tuple[str, str] | None) -> Path:
    fixture: dict[str, dict[str, object]] = {}
    for symbol in ("000001.SZ", "600000.SH"):
        fixture[symbol] = {
            "fundamentals": [_record(symbol, "akshare_fundamental", "2026-06-03")],
            "financial_statements": [
                _record(symbol, "akshare_financial_statement", "2026-04-24")
            ],
            "capital_flow": [_record(symbol, "akshare_fund_flow", "2026-06-03")],
        }
    if fail_scope is not None:
        symbol, group = fail_scope
        fixture[symbol][group] = {"error": "fixture timeout"}
    path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
    return path


def _record(symbol: str, source: str, published_at: str) -> dict[str, object]:
    return {
        "symbol": symbol,
        "sector": None,
        "published_at": published_at,
        "source": source,
        "category": "stock_data",
        "title": f"{symbol} {source}",
        "url": "",
        "summary": "fixture=1",
        "risk_tags": ["selected_universe"],
        "metadata": {},
    }
