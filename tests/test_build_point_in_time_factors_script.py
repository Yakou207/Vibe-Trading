from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path


def test_build_point_in_time_factors_writes_processed_tables_and_manifest(tmp_path: Path) -> None:
    from fintech_quant.data.run_artifacts import RunArtifactStore, sha256_file

    raw_root = tmp_path / "raw"
    raw_store = RunArtifactStore(raw_root, "raw-1", layer="raw")
    raw_store.write_jsonl(
        "fundamentals/000001.SZ.jsonl",
        [
            _record_json(
                source="akshare_fundamental",
                published_at="2023-04-25",
                summary="pe=18.0; pb=1.5",
                risk_tags=["selected_universe", "fundamental", "valuation"],
                metadata={"record_kind": "valuation", "available_date_source": "row_date"},
            ),
            _record_json(
                source="akshare_fundamental",
                published_at="2023-03-31",
                summary="roe=0.16; growth=0.12",
                risk_tags=["selected_universe", "financial_indicator", "unverified_availability"],
                metadata={
                    "record_kind": "financial_indicator",
                    "report_period": "2023-03-31",
                    "availability_verified": False,
                },
            ),
        ],
    )
    raw_store.write_jsonl(
        "financial_statements/000001.SZ.jsonl",
        [
            _record_json(
                source="akshare_financial_statement",
                published_at="2023-04-24",
                summary="goodwill=100; total_assets=1000",
                risk_tags=["selected_universe", "financial_statement", "balance_sheet"],
                metadata={
                    "statement_type": "资产负债表",
                    "report_period": "2023-03-31",
                    "available_date_source": "更新日期",
                },
            )
        ],
    )
    raw_store.write_jsonl(
        "capital_flow/000001.SZ.jsonl",
        [
            _record_json(
                source="akshare_fund_flow",
                published_at="2023-04-25",
                summary="main_net_inflow=1000",
                risk_tags=["selected_universe", "capital_flow"],
                metadata={},
            )
        ],
    )
    scopes = [
        {"symbol": "000001.SZ", "group": group, "status": "success"}
        for group in ("fundamentals", "financial_statements", "capital_flow")
    ]
    raw_manifest = raw_store.write_manifest(
        request={"symbols": ["000001.SZ"]},
        scopes=scopes,
        created_at="2026-07-10T12:00:00+08:00",
        git_sha="abc123",
        provider_versions={"fixture": "1"},
    )
    calendar_path = tmp_path / "calendar.csv"
    calendar_path.write_text("trade_date\n2023-04-24\n2023-04-25\n", encoding="utf-8")
    processed_root = tmp_path / "processed"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_point_in_time_factors.py",
            "--raw-manifest",
            str(raw_manifest),
            "--trading-calendar",
            str(calendar_path),
            "--run-id",
            "processed-1",
            "--processed-root",
            str(processed_root),
            "--created-at",
            "2026-07-10T12:30:00+08:00",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    manifest_path = processed_root / "processed-1/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["request"]["parent_manifest_sha256"] == sha256_file(raw_manifest)
    assert {artifact["path"] for artifact in manifest["artifacts"]} == {
        "fundamentals.csv",
        "capital_flow.csv",
    }
    with (processed_root / "processed-1/fundamentals.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        fundamentals = list(csv.DictReader(handle))
    assert fundamentals[-1]["available_date"] == "2023-04-25"
    assert fundamentals[-1]["roe"] == "0.16"


def test_build_point_in_time_factors_rejects_tampered_raw_artifact(tmp_path: Path) -> None:
    from fintech_quant.data.run_artifacts import RunArtifactStore

    raw_store = RunArtifactStore(tmp_path / "raw", "raw-1", layer="raw")
    artifact_path = raw_store.write_jsonl(
        "fundamentals/000001.SZ.jsonl",
        [
            _record_json(
                source="akshare_fundamental",
                published_at="2023-04-25",
                summary="pe=18.0; pb=1.5",
                risk_tags=["selected_universe", "fundamental", "valuation"],
                metadata={"record_kind": "valuation", "available_date_source": "row_date"},
            )
        ],
    )
    raw_manifest = raw_store.write_manifest(
        request={"symbols": ["000001.SZ"]},
        scopes=[{"symbol": "000001.SZ", "group": "fundamentals", "status": "success"}],
        created_at="2026-07-10T12:00:00+08:00",
        git_sha="abc123",
        provider_versions={"fixture": "1"},
    )
    artifact_path.write_text("tampered\n", encoding="utf-8")
    calendar_path = tmp_path / "calendar.csv"
    calendar_path.write_text("trade_date\n2023-04-25\n", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_point_in_time_factors.py",
            "--raw-manifest",
            str(raw_manifest),
            "--trading-calendar",
            str(calendar_path),
            "--run-id",
            "processed-1",
            "--processed-root",
            str(tmp_path / "processed"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "raw artifact hash mismatch" in completed.stderr


def _record_json(
    *,
    source: str,
    published_at: str,
    summary: str,
    risk_tags: list[str],
    metadata: dict[str, object],
) -> dict[str, object]:
    return {
        "symbol": "000001.SZ",
        "sector": None,
        "published_at": published_at,
        "source": source,
        "category": "stock_data",
        "title": f"{source} {published_at}",
        "url": "",
        "summary": summary,
        "risk_tags": risk_tags,
        "metadata": metadata,
    }
