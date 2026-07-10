from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_run_csi300_research_writes_formal_point_in_time_outputs(tmp_path: Path) -> None:
    from fintech_quant.data.run_artifacts import RunArtifactStore, sha256_file

    membership = tmp_path / "membership.csv"
    membership.write_text(
        "index_code,symbol,member_from,member_to,source,fetched_at\n"
        "000300,000001.SZ,2025-01-01,,fixture,2026-07-10T12:00:00+08:00\n"
        "000300,600000.SH,2025-01-01,,fixture,2026-07-10T12:00:00+08:00\n",
        encoding="utf-8",
    )
    benchmark = tmp_path / "benchmark.csv"
    benchmark.write_text(
        "trade_date,index_close\n"
        "2026-01-02,4000\n"
        "2026-01-05,4040\n"
        "2026-01-06,4020\n",
        encoding="utf-8",
    )
    raw_store = RunArtifactStore(tmp_path / "raw", "raw-1", layer="raw")
    raw_manifest = raw_store.write_manifest(
        request={
            "membership": str(membership.resolve()),
            "membership_sha256": sha256_file(membership),
            "symbols": ["000001.SZ", "600000.SH"],
        },
        scopes=[],
        created_at="2026-07-10T12:00:00+08:00",
        git_sha="fixture-sha",
        provider_versions={"fixture": "1"},
    )

    processed_store = RunArtifactStore(
        tmp_path / "processed",
        "processed-1",
        layer="processed",
        parent_manifest=str(raw_manifest.resolve()),
    )
    processed_store.write_csv(
        "fundamentals.csv",
        [
            {
                "symbol": "000001.SZ",
                "available_date": "2026-01-01",
                "pe": 18,
                "pb": 1.5,
                "roe": 0.16,
                "growth": 0.12,
            },
            {
                "symbol": "600000.SH",
                "available_date": "2026-01-01",
                "pe": 80,
                "pb": 8,
                "roe": 0.01,
                "growth": -0.10,
            },
        ],
        fieldnames=("symbol", "available_date", "pe", "pb", "roe", "growth"),
    )
    processed_store.write_csv(
        "capital_flow.csv",
        [
            {
                "symbol": symbol,
                "available_date": trade_date,
                "main_net_inflow": 1000 if symbol == "000001.SZ" else -1000,
                "main_outflow_days": 0 if symbol == "000001.SZ" else 5,
                "margin_financing_positive": symbol == "000001.SZ",
            }
            for trade_date in ("2026-01-02", "2026-01-05", "2026-01-06")
            for symbol in ("000001.SZ", "600000.SH")
        ],
        fieldnames=(
            "symbol",
            "available_date",
            "main_net_inflow",
            "main_outflow_days",
            "margin_financing_positive",
        ),
    )
    processed_manifest = processed_store.write_manifest(
        request={
            "parent_run_id": "raw-1",
            "parent_manifest_sha256": sha256_file(raw_manifest),
            "trading_calendar": str(benchmark.resolve()),
            "trading_calendar_sha256": sha256_file(benchmark),
        },
        scopes=[],
        created_at="2026-07-10T12:30:00+08:00",
        git_sha="fixture-sha",
        provider_versions={"fixture": "1"},
    )

    features = tmp_path / "features.csv"
    features.write_text(_features_csv(), encoding="utf-8")
    output_root = tmp_path / "outputs"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_csi300_research.py",
            "--processed-manifest",
            str(processed_manifest),
            "--features",
            str(features),
            "--benchmark",
            str(benchmark),
            "--run-id",
            "fixture-csi300",
            "--expected-members",
            "2",
            "--fundamental-warmup-days",
            "0",
            "--output-root",
            str(output_root),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    run_dir = output_root / "fixture-csi300"
    expected = {
        "data_health.json",
        "scoring_coverage.json",
        "stock_score_analysis.json",
        "baseline/run_report.json",
        "risk_controlled/run_report.json",
        "rl_state_dataset.jsonl",
        "benchmark_comparison.json",
        "manifest.json",
    }
    assert all((run_dir / relative).exists() for relative in expected)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["data_health_passed"] is True
    assert manifest["dqn_overlay_status"] == "diagnostic_only"
    assert manifest["inputs"]["processed_manifest"]["sha256"] == sha256_file(processed_manifest)

    failed = subprocess.run(
        [
            sys.executable,
            "scripts/run_csi300_research.py",
            "--processed-manifest",
            str(processed_manifest),
            "--features",
            str(features),
            "--benchmark",
            str(benchmark),
            "--run-id",
            "failed-health",
            "--expected-members",
            "3",
            "--fundamental-warmup-days",
            "0",
            "--output-root",
            str(output_root),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    failed_dir = output_root / "failed-health"
    assert failed.returncode == 2
    assert (failed_dir / "data_health.json").exists()
    assert not (failed_dir / "baseline").exists()


def _features_csv() -> str:
    header = (
        "symbol,trade_date,open,high,low,close,volume,amount,source,return_1d,ma20,ma60,ma250,"
        "close_above_ma20,close_above_ma60,close_above_ma250,rsi14,macd_line,macd_signal,"
        "macd_hist,macd_positive,volatility20,return_20d,rs_rank_20d\n"
    )
    rows = []
    for trade_date, good_close, weak_close in (
        ("2026-01-02", 10.0, 10.0),
        ("2026-01-05", 10.5, 9.8),
        ("2026-01-06", 10.7, 9.6),
    ):
        rows.append(
            f"000001.SZ,{trade_date},{good_close},{good_close},{good_close},{good_close},1000,10000,fixture,"
            "0.01,9,8,7,true,true,true,55,0.1,0.05,0.05,true,0.02,0.10,0.90\n"
        )
        rows.append(
            f"600000.SH,{trade_date},{weak_close},{weak_close},{weak_close},{weak_close},1000,10000,fixture,"
            "-0.01,11,12,13,false,false,false,35,-0.1,-0.05,-0.05,false,0.03,-0.10,0.10\n"
        )
    return header + "".join(rows)
