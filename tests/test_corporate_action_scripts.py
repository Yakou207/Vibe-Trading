from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path


def test_collect_and_build_corporate_actions_preserve_raw_and_normalize_terms(
    tmp_path: Path,
) -> None:
    membership = tmp_path / "membership.csv"
    membership.write_text("symbol\n000001.SZ\n", encoding="utf-8")
    fixture = tmp_path / "fixture.json"
    fixture.write_text(
        json.dumps(
            {
                "000001.SZ": [
                    {
                        "实施方案公告日期": "2026-06-05",
                        "股权登记日": "2026-06-11",
                        "除权日": "2026-06-12",
                        "派息比例": 3.6,
                        "送股比例": 2.0,
                        "转增比例": 1.0,
                    },
                    {
                        "_action_type": "rights_issue",
                        "公告日期": "2026-07-01",
                        "除权基准日": "2026-07-10",
                        "配股上市日": "2026-07-20",
                        "配股比例": 2.0,
                        "配股价格": 8.0,
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    collected = subprocess.run(
        [
            sys.executable,
            "scripts/collect_corporate_actions.py",
            "--source",
            "fixture",
            "--fixture-input",
            str(fixture),
            "--membership",
            str(membership),
            "--start",
            "2026-01-01",
            "--end",
            "2026-12-31",
            "--run-id",
            "actions-raw",
            "--raw-root",
            str(tmp_path / "raw"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert collected.returncode == 0, collected.stderr
    raw_manifest = tmp_path / "raw/actions-raw/manifest.json"
    raw_payload = json.loads(raw_manifest.read_text(encoding="utf-8"))
    assert raw_payload["artifacts"][0]["path"] == "corporate_actions/000001.SZ.jsonl"

    built = subprocess.run(
        [
            sys.executable,
            "scripts/build_corporate_actions.py",
            "--raw-manifest",
            str(raw_manifest),
            "--run-id",
            "actions-processed",
            "--processed-root",
            str(tmp_path / "processed"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    output = tmp_path / "processed/actions-processed/corporate_actions.csv"
    with output.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {
            "symbol": "000001.SZ",
            "ex_date": "2026-06-12",
            "action_type": "distribution",
            "cash_dividend_per_share": "0.36",
            "share_multiplier": "1.3",
            "rights_ratio": "0.0",
            "rights_price": "0.0",
            "listing_date": "",
            "source": "akshare_cninfo_dividend",
        },
        {
            "symbol": "000001.SZ",
            "ex_date": "2026-07-10",
            "action_type": "rights_issue",
            "cash_dividend_per_share": "0.0",
            "share_multiplier": "1.0",
            "rights_ratio": "0.2",
            "rights_price": "8.0",
            "listing_date": "2026-07-20",
            "source": "akshare_cninfo_rights_issue",
        },
    ]


def test_collect_corporate_actions_appends_a_new_raw_delta_without_reusing_parent(
    tmp_path: Path,
) -> None:
    membership = tmp_path / "membership.csv"
    membership.write_text("symbol\n000001.SZ\n", encoding="utf-8")
    first_fixture = tmp_path / "first.json"
    first_fixture.write_text(
        json.dumps({"000001.SZ": [_distribution("2026-06-12", 3.6)]}),
        encoding="utf-8",
    )
    first = _run_action_collector(tmp_path, membership, first_fixture, "actions-1")
    assert first.returncode == 0, first.stderr

    child_fixture = tmp_path / "child.json"
    child_fixture.write_text(
        json.dumps({"000001.SZ": [_distribution("2026-07-10", 2.0)]}),
        encoding="utf-8",
    )
    parent_manifest = tmp_path / "raw/actions-1/manifest.json"
    child = _run_action_collector(
        tmp_path,
        membership,
        child_fixture,
        "actions-2",
        append_from=parent_manifest,
        start="2026-07-01",
        end="2026-07-31",
    )

    assert child.returncode == 0, child.stderr
    manifest = json.loads((tmp_path / "raw/actions-2/manifest.json").read_text(encoding="utf-8"))
    assert manifest["parent_manifest"] == str(parent_manifest.resolve())
    assert manifest["scopes"][0]["status"] == "success"
    assert "fetched_scopes=1" in child.stdout
    assert "reused_scopes=0" in child.stdout
    rows = (tmp_path / "raw/actions-2/corporate_actions/000001.SZ.jsonl").read_text(
        encoding="utf-8"
    )
    assert "2026-07-10" in rows
    assert "2026-06-12" not in rows


def test_build_corporate_actions_includes_parent_future_event_when_child_end_reaches_it(
    tmp_path: Path,
) -> None:
    from fintech_quant.data.run_artifacts import RunArtifactStore

    parent_store = RunArtifactStore(tmp_path / "raw", "parent", layer="raw")
    parent_store.write_jsonl(
        "corporate_actions/000001.SZ.jsonl",
        [{"symbol": "000001.SZ", **_distribution("2026-07-10", 2.0)}],
    )
    parent_manifest = parent_store.write_manifest(
        request={
            "start": "2026-01-01",
            "end": "2026-06-30",
            "action_types": ["distribution", "rights_issue"],
        },
        scopes=[],
        created_at="2026-06-30T17:30:00+08:00",
        git_sha="parent",
        provider_versions={"fixture": "1"},
    )
    child_store = RunArtifactStore(
        tmp_path / "raw",
        "child",
        layer="raw",
        parent_manifest=str(parent_manifest),
    )
    child_store.write_jsonl("corporate_actions/000001.SZ.jsonl", [])
    child_manifest = child_store.write_manifest(
        request={
            "start": "2026-07-01",
            "end": "2026-07-13",
            "action_types": ["distribution", "rights_issue"],
        },
        scopes=[],
        created_at="2026-07-13T17:30:00+08:00",
        git_sha="child",
        provider_versions={"fixture": "1"},
    )

    built = subprocess.run(
        [
            sys.executable,
            "scripts/build_corporate_actions.py",
            "--raw-manifest",
            str(child_manifest),
            "--run-id",
            "actions",
            "--processed-root",
            str(tmp_path / "processed"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert built.returncode == 0, built.stderr
    with (tmp_path / "processed/actions/corporate_actions.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert [(row["symbol"], row["ex_date"]) for row in rows] == [
        ("000001.SZ", "2026-07-10")
    ]
    manifest = json.loads(
        (tmp_path / "processed/actions/manifest.json").read_text(encoding="utf-8")
    )
    assert len(manifest["request"]["raw_manifest_chain"]) == 2


def _run_action_collector(
    root: Path,
    membership: Path,
    fixture: Path,
    run_id: str,
    *,
    append_from: Path | None = None,
    start: str = "2026-01-01",
    end: str = "2026-12-31",
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "scripts/collect_corporate_actions.py",
        "--source",
        "fixture",
        "--fixture-input",
        str(fixture),
        "--membership",
        str(membership),
        "--start",
        start,
        "--end",
        end,
        "--run-id",
        run_id,
        "--raw-root",
        str(root / "raw"),
    ]
    if append_from is not None:
        command.extend(["--append-from", str(append_from)])
    return subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )


def _distribution(ex_date: str, cash_per_ten: float) -> dict[str, object]:
    return {
        "实施方案公告日期": ex_date,
        "股权登记日": ex_date,
        "除权日": ex_date,
        "派息比例": cash_per_ten,
        "送股比例": 0.0,
        "转增比例": 0.0,
    }
