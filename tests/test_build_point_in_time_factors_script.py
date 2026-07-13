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


def test_build_point_in_time_factors_can_explicitly_build_price_volume_proxy(tmp_path: Path) -> None:
    from fintech_quant.data.run_artifacts import RunArtifactStore, sha256_file

    raw_store = RunArtifactStore(tmp_path / "raw", "raw-1", layer="raw")
    raw_manifest = raw_store.write_manifest(
        request={"symbols": ["000001.SZ"]},
        scopes=[],
        created_at="2026-07-10T12:00:00+08:00",
        git_sha="abc123",
        provider_versions={"fixture": "1"},
    )
    features_path = tmp_path / "features.csv"
    features_path.write_text(
        "symbol,trade_date,open,high,low,close,volume,amount,source\n"
        "000001.SZ,2026-01-02,10,11,9,10,100,1000,fixture\n"
        "000001.SZ,2026-01-05,11,11,9,11,200,2200,fixture\n"
        "000001.SZ,2026-01-06,9,11,9,9,100,900,fixture\n",
        encoding="utf-8",
    )
    processed_root = tmp_path / "processed"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_point_in_time_factors.py",
            "--raw-manifest",
            str(raw_manifest),
            "--trading-calendar",
            str(features_path),
            "--capital-flow-mode",
            "price-volume-proxy",
            "--price-features",
            str(features_path),
            "--price-volume-window",
            "3",
            "--run-id",
            "processed-1",
            "--processed-root",
            str(processed_root),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    manifest = json.loads((processed_root / "processed-1/manifest.json").read_text(encoding="utf-8"))
    assert manifest["request"]["capital_flow_mode"] == "price-volume-proxy"
    assert manifest["request"]["price_features_sha256"] == sha256_file(features_path)
    with (processed_root / "processed-1/capital_flow.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["source"] == "derived_price_volume_cmf_obv_v1"
    assert rows[0]["flow_proxy_kind"] == "price_volume_cmf_obv"
    assert rows[0]["main_net_inflow"] == ""


def test_build_point_in_time_factors_merges_parent_records_before_materializing(
    tmp_path: Path,
) -> None:
    from fintech_quant.data.run_artifacts import RunArtifactStore

    parent_store = RunArtifactStore(tmp_path / "raw", "parent", layer="raw")
    parent_store.write_jsonl(
        "financial_statements/000001.SZ.jsonl",
        [
            _record_json(
                source="akshare_financial_statement",
                published_at="2026-01-03",
                summary="net_profit=12; total_assets=100; total_liabilities=0; revenue=50",
                risk_tags=["selected_universe", "financial_statement"],
                metadata={
                    "record_kind": "financial_statement",
                    "statement_type": "利润表",
                    "report_period": "2025-12-31",
                    "available_date_source": "更新日期",
                },
            )
        ],
    )
    parent_store.write_jsonl(
        "fundamentals/000001.SZ.jsonl",
        [
            _record_json(
                source="akshare_fundamental",
                published_at="2026-01-02",
                summary="pe=10; pb=1",
                risk_tags=["selected_universe", "valuation"],
                metadata={"record_kind": "valuation", "available_date_source": "row_date"},
            )
        ],
    )
    parent_manifest = parent_store.write_manifest(
        request={"start": "2026-01-01", "end": "2026-01-03"},
        scopes=[],
        created_at="2026-01-03T17:30:00+08:00",
        git_sha="parent",
        provider_versions={"fixture": "1"},
    )
    child_store = RunArtifactStore(
        tmp_path / "raw",
        "child",
        layer="raw",
        parent_manifest=str(parent_manifest),
    )
    child_store.write_jsonl(
        "fundamentals/000001.SZ.jsonl",
        [
            _record_json(
                source="akshare_fundamental",
                published_at="2026-01-05",
                summary="pe=9; pb=0.9",
                risk_tags=["selected_universe", "valuation"],
                metadata={"record_kind": "valuation", "available_date_source": "row_date"},
            )
        ],
    )
    child_manifest = child_store.write_manifest(
        request={"start": "2026-01-05", "end": "2026-01-05"},
        scopes=[],
        created_at="2026-01-05T17:30:00+08:00",
        git_sha="child",
        provider_versions={"fixture": "1"},
    )
    calendar = tmp_path / "calendar.csv"
    calendar.write_text("trade_date\n2026-01-02\n2026-01-05\n", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_point_in_time_factors.py",
            "--raw-manifest",
            str(child_manifest),
            "--trading-calendar",
            str(calendar),
            "--run-id",
            "factors",
            "--processed-root",
            str(tmp_path / "processed"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    with (tmp_path / "processed/factors/fundamentals.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert rows[-1]["available_date"] == "2026-01-05"
    assert rows[-1]["pe"] == "9.0"
    assert rows[-1]["roe"] == "0.12"
    manifest = json.loads(
        (tmp_path / "processed/factors/manifest.json").read_text(encoding="utf-8")
    )
    assert len(manifest["request"]["raw_manifest_chain"]) == 2


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
