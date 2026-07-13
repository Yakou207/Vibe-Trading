from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_same_inputs_and_commit_produce_identical_factor_and_score_hashes(tmp_path: Path) -> None:
    from fintech_quant.data.run_artifacts import sha256_file

    first = _run_fixture_pipeline(tmp_path / "first")
    second = _run_fixture_pipeline(tmp_path / "second")

    assert first["factor_hashes"] == second["factor_hashes"]
    assert first["score_hashes"] == second["score_hashes"]
    assert all(len(value) == 64 for value in first["factor_hashes"].values())
    assert first["score_hashes"]["coverage"] == sha256_file(
        tmp_path / "first/outputs/formal/scoring_coverage.json"
    )


def _run_fixture_pipeline(root: Path) -> dict[str, dict[str, str]]:
    from fintech_quant.data.run_artifacts import sha256_file

    root.mkdir(parents=True)
    membership = root / "membership.csv"
    membership.write_text(
        "index_code,symbol,member_from,member_to,source,source_fetched_at\n"
        "000300,000001.SZ,2025-01-01,,fixture,2026-07-10T12:00:00+08:00\n"
        "000300,600000.SH,2025-01-01,,fixture,2026-07-10T12:00:00+08:00\n",
        encoding="utf-8",
    )
    benchmark = root / "benchmark.csv"
    benchmark.write_text(
        "trade_date,index_close\n"
        "2026-01-01,3980\n"
        "2026-01-02,4000\n"
        "2026-01-05,4040\n"
        "2026-01-06,4020\n",
        encoding="utf-8",
    )
    fixture = root / "factor_fixture.json"
    fixture.write_text(
        json.dumps(_factor_fixture(), ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    signal_dir = root / "signal"
    signal_dir.mkdir()
    features = signal_dir / "features.csv"
    features.write_text(_features_csv(), encoding="utf-8")
    signal_manifest = signal_dir / "manifest.json"
    signal_manifest.write_text(
        json.dumps(
            {
                "layer": "processed",
                "request": {"adjust": "hfq"},
                "artifacts": [{"path": "features.csv", "sha256": sha256_file(features)}],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    execution_dir = root / "execution"
    execution_dir.mkdir()
    execution_prices = execution_dir / "daily.csv"
    execution_prices.write_text(_features_csv(), encoding="utf-8")
    execution_manifest = execution_dir / "manifest.json"
    execution_manifest.write_text(
        json.dumps(
            {
                "layer": "processed",
                "request": {"adjust": "none"},
                "artifacts": [{"path": "daily.csv", "sha256": sha256_file(execution_prices)}],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    action_dir = root / "actions"
    action_dir.mkdir()
    corporate_actions = action_dir / "corporate_actions.csv"
    corporate_actions.write_text(
        "symbol,ex_date,cash_dividend_per_share,share_multiplier,source\n"
        "000001.SZ,2026-01-05,0.01,1.0,fixture\n",
        encoding="utf-8",
    )
    action_manifest = action_dir / "manifest.json"
    action_manifest.write_text(
        json.dumps(
            {
                "layer": "processed",
                "request": {"action_types": ["distribution", "rights_issue"]},
                "artifacts": [
                    {
                        "path": "corporate_actions.csv",
                        "sha256": sha256_file(corporate_actions),
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    raw_root = root / "raw"
    _run(
        [
            "scripts/collect_point_in_time_factors.py",
            "--source",
            "fixture",
            "--fixture-input",
            str(fixture),
            "--membership",
            str(membership),
            "--start",
            "2026-01-01",
            "--end",
            "2026-01-06",
            "--run-id",
            "raw",
            "--raw-root",
            str(raw_root),
            "--created-at",
            "2026-07-10T12:00:00+08:00",
        ]
    )
    processed_root = root / "processed"
    _run(
        [
            "scripts/build_point_in_time_factors.py",
            "--raw-manifest",
            str(raw_root / "raw/manifest.json"),
            "--trading-calendar",
            str(benchmark),
            "--run-id",
            "processed",
            "--processed-root",
            str(processed_root),
            "--created-at",
            "2026-07-10T12:30:00+08:00",
        ]
    )
    output_root = root / "outputs"
    _run(
        [
            "scripts/run_csi300_research.py",
            "--processed-manifest",
            str(processed_root / "processed/manifest.json"),
            "--signal-price-manifest",
            str(signal_manifest),
            "--execution-price-manifest",
            str(execution_manifest),
            "--corporate-action-manifest",
            str(action_manifest),
            "--benchmark",
            str(benchmark),
            "--run-id",
            "formal",
            "--expected-members",
            "2",
            "--fundamental-warmup-days",
            "0",
            "--output-root",
            str(output_root),
            "--created-at",
            "2026-07-10T13:00:00+08:00",
        ]
    )
    return {
        "factor_hashes": {
            name: sha256_file(processed_root / f"processed/{name}.csv")
            for name in ("fundamentals", "capital_flow")
        },
        "score_hashes": {
            "coverage": sha256_file(output_root / "formal/scoring_coverage.json"),
            "analysis": sha256_file(output_root / "formal/stock_score_analysis.json"),
            "rl_state": sha256_file(output_root / "formal/rl_state_dataset.jsonl"),
        },
    }


def _run(arguments: list[str]) -> None:
    completed = subprocess.run(
        [sys.executable, *arguments],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def _factor_fixture() -> dict[str, dict[str, list[dict[str, object]]]]:
    fixture: dict[str, dict[str, list[dict[str, object]]]] = {}
    for good, symbol in ((True, "000001.SZ"), (False, "600000.SH")):
        fixture[symbol] = {
            "fundamentals": [
                _record(
                    symbol,
                    source="akshare_fundamental",
                    published_at="2026-01-01",
                    summary="pe=18; pb=1.5" if good else "pe=80; pb=8",
                    metadata={"record_kind": "valuation", "available_date_source": "row_date"},
                ),
                _record(
                    symbol,
                    source="akshare_fundamental",
                    published_at="2025-12-31",
                    summary="roe=0.16; growth=0.12" if good else "roe=0.01; growth=-0.10",
                    metadata={
                        "record_kind": "financial_indicator",
                        "report_period": "2025-12-31",
                        "availability_verified": False,
                    },
                ),
            ],
            "financial_statements": [
                _record(
                    symbol,
                    source="akshare_financial_statement",
                    published_at="2026-01-01",
                    summary="goodwill=10; total_assets=1000",
                    metadata={
                        "statement_type": "资产负债表",
                        "report_period": "2025-12-31",
                        "available_date_source": "更新日期",
                    },
                )
            ],
            "capital_flow": [
                _record(
                    symbol,
                    source="akshare_fund_flow",
                    published_at=trade_date,
                    summary=f"main_net_inflow={1000 if good else -1000}",
                    metadata={},
                )
                for trade_date in ("2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06")
            ],
        }
    return fixture


def _record(
    symbol: str,
    *,
    source: str,
    published_at: str,
    summary: str,
    metadata: dict[str, object],
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "sector": None,
        "published_at": published_at,
        "source": source,
        "category": "stock_data",
        "title": f"{symbol} {source} {published_at}",
        "url": "",
        "summary": summary,
        "risk_tags": ["selected_universe"],
        "metadata": metadata,
    }


def _features_csv() -> str:
    header = (
        "symbol,trade_date,open,high,low,close,volume,amount,source,return_1d,ma20,ma60,ma250,"
        "close_above_ma20,close_above_ma60,close_above_ma250,rsi14,macd_line,macd_signal,"
        "macd_hist,macd_positive,volatility20,return_20d,rs_rank_20d\n"
    )
    rows: list[str] = []
    for trade_date, good_close, weak_close in (
        ("2026-01-02", 10.0, 10.0),
        ("2026-01-05", 10.5, 9.8),
        ("2026-01-06", 10.7, 9.6),
    ):
        rows.append(
            f"000001.SZ,{trade_date},{good_close},{good_close},{good_close},{good_close},"
            "1000,10000,fixture,0.01,9,8,7,true,true,true,55,0.1,0.05,0.05,true,0.02,0.10,0.90\n"
        )
        rows.append(
            f"600000.SH,{trade_date},{weak_close},{weak_close},{weak_close},{weak_close},"
            "1000,10000,fixture,-0.01,11,12,13,false,false,false,35,-0.1,-0.05,-0.05,false,"
            "0.03,-0.10,0.10\n"
        )
    return header + "".join(rows)
