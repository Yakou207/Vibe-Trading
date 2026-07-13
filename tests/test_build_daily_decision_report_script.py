from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_build_daily_decision_report_script_writes_small_verified_report(
    tmp_path: Path,
) -> None:
    inputs = _write_inputs(tmp_path, fresh_benchmark=True)
    output = tmp_path / "daily_decision.json"
    health = tmp_path / "data_health.json"

    completed = _run_script(inputs, output=output, health=health)

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["as_of"] == "2026-01-05"
    assert payload["active_member_count"] == 2
    assert len(payload["scores"]) == 2
    assert payload["data_health_passed"] is True
    assert payload["git_sha"]
    assert set(payload["inputs"]) == {
        "benchmark",
        "corporate_action_manifest",
        "corporate_actions",
        "execution_price_manifest",
        "execution_prices",
        "factor_manifest",
        "features",
        "fundamentals",
        "capital_flow",
        "membership",
        "signal_price_manifest",
    }
    assert json.loads(health.read_text(encoding="utf-8"))["passed"] is True


def test_build_daily_decision_report_script_rejects_stale_benchmark_without_report(
    tmp_path: Path,
) -> None:
    inputs = _write_inputs(tmp_path, fresh_benchmark=False)
    output = tmp_path / "daily_decision.json"
    health = tmp_path / "data_health.json"

    completed = _run_script(inputs, output=output, health=health)

    assert completed.returncode != 0
    assert "benchmark row is missing index_close" in completed.stderr
    assert not output.exists()
    assert health.exists()


def _run_script(
    inputs: dict[str, Path],
    *,
    output: Path,
    health: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/build_daily_decision_report.py",
            "--factor-manifest",
            str(inputs["factor_manifest"]),
            "--signal-price-manifest",
            str(inputs["signal_manifest"]),
            "--execution-price-manifest",
            str(inputs["execution_manifest"]),
            "--corporate-action-manifest",
            str(inputs["action_manifest"]),
            "--benchmark",
            str(inputs["benchmark"]),
            "--membership",
            str(inputs["membership"]),
            "--as-of",
            "2026-01-05",
            "--expected-members",
            "2",
            "--fundamental-warmup-days",
            "0",
            "--minimum-price-coverage",
            "1",
            "--minimum-fundamental-coverage",
            "1",
            "--minimum-capital-flow-coverage",
            "1",
            "--output",
            str(output),
            "--data-health-output",
            str(health),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )


def _write_inputs(root: Path, *, fresh_benchmark: bool) -> dict[str, Path]:
    from fintech_quant.data.research_dataset import DAILY_BAR_FIELDS, OUTPUT_FEATURE_FIELDS
    from fintech_quant.data.run_artifacts import RunArtifactStore, sha256_file
    from fintech_quant.data.factor_store import CAPITAL_FLOW_FIELDS, FUNDAMENTAL_FIELDS

    symbols = ("000001.SZ", "600000.SH")
    dates = ("2026-01-02", "2026-01-05")
    membership = root / "membership.csv"
    membership.write_text(
        "index_code,symbol,member_from,member_to,source,source_fetched_at\n"
        + "".join(
            f"000300,{symbol},2026-01-01,,fixture,2026-01-01T00:00:00+08:00\n"
            for symbol in symbols
        ),
        encoding="utf-8",
    )
    benchmark = root / "benchmark.csv"
    benchmark_dates = dates if fresh_benchmark else dates[:1]
    benchmark.write_text(
        "trade_date,index_symbol,index_close,index_ma250,index_below_annual_ma\n"
        + "".join(f"{trade_date},sh000300,4000,3900,false\n" for trade_date in benchmark_dates),
        encoding="utf-8",
    )

    signal = RunArtifactStore(root / "processed", "signal", layer="processed")
    signal.write_csv(
        "features.csv",
        [
            _feature(symbol, trade_date, index)
            for trade_date in dates
            for index, symbol in enumerate(symbols)
        ],
        fieldnames=OUTPUT_FEATURE_FIELDS,
    )
    signal_manifest = signal.write_manifest(
        request={"adjust": "hfq", "start": dates[0], "end": dates[-1]},
        scopes=[],
        created_at="2026-01-05T17:30:00+08:00",
        git_sha="fixture",
        provider_versions={"fixture": "1"},
    )

    execution = RunArtifactStore(root / "processed", "execution", layer="processed")
    execution.write_csv(
        "daily.csv",
        [_daily(symbol, trade_date) for trade_date in dates for symbol in symbols],
        fieldnames=DAILY_BAR_FIELDS,
    )
    execution_manifest = execution.write_manifest(
        request={"adjust": "none", "start": dates[0], "end": dates[-1]},
        scopes=[],
        created_at="2026-01-05T17:30:00+08:00",
        git_sha="fixture",
        provider_versions={"fixture": "1"},
    )

    factors = RunArtifactStore(root / "processed", "factors", layer="processed")
    factors.write_csv(
        "fundamentals.csv",
        [_fundamental(symbol, index) for index, symbol in enumerate(symbols)],
        fieldnames=FUNDAMENTAL_FIELDS,
    )
    factors.write_csv(
        "capital_flow.csv",
        [_capital_flow(symbol, index) for index, symbol in enumerate(symbols)],
        fieldnames=CAPITAL_FLOW_FIELDS,
    )
    factor_manifest = factors.write_manifest(
        request={"trading_calendar_sha256": sha256_file(benchmark)},
        scopes=[],
        created_at="2026-01-05T17:30:00+08:00",
        git_sha="fixture",
        provider_versions={"fixture": "1"},
    )

    actions = RunArtifactStore(root / "processed", "actions", layer="processed")
    actions.write_csv(
        "corporate_actions.csv",
        [],
        fieldnames=(
            "symbol",
            "ex_date",
            "action_type",
            "cash_dividend_per_share",
            "share_multiplier",
            "rights_ratio",
            "rights_price",
            "listing_date",
            "source",
        ),
    )
    action_manifest = actions.write_manifest(
        request={
            "start": dates[0],
            "end": dates[-1],
            "action_types": ["distribution", "rights_issue"],
        },
        scopes=[],
        created_at="2026-01-05T17:30:00+08:00",
        git_sha="fixture",
        provider_versions={"fixture": "1"},
    )
    return {
        "membership": membership,
        "benchmark": benchmark,
        "signal_manifest": signal_manifest,
        "execution_manifest": execution_manifest,
        "factor_manifest": factor_manifest,
        "action_manifest": action_manifest,
    }


def _feature(symbol: str, trade_date: str, index: int) -> dict[str, object]:
    return {
        **_daily(symbol, trade_date),
        "return_1d": 0.01,
        "return_20d": 0.1,
        "rs_rank_20d": 0.8,
        "ma20": 9.0,
        "ma60": 8.0,
        "ma250": 7.0,
        "close_above_ma20": True,
        "close_above_ma60": True,
        "close_above_ma250": True,
        "rsi14": 55.0,
        "macd_line": 1.0,
        "macd_signal": 0.5,
        "macd_hist": 0.5,
        "macd_positive": True,
        "volatility20": 0.1,
        "limit_up_streak": index,
    }


def _daily(symbol: str, trade_date: str) -> dict[str, object]:
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.0,
        "volume": 1000.0,
        "amount": 10000.0,
        "source": "fixture",
    }


def _fundamental(symbol: str, index: int) -> dict[str, object]:
    good = index == 0
    return {
        "symbol": symbol,
        "report_period": "2025-12-31",
        "available_date": "2026-01-02",
        "source": "fixture",
        "source_fetched_at": "2026-01-05T17:30:00+08:00",
        "pe": 10.0 if good else 80.0,
        "pb": 1.0 if good else 8.0,
        "roe": 0.2 if good else -0.1,
        "growth": 0.2 if good else -0.1,
        "goodwill_ratio": 0.0,
    }


def _capital_flow(symbol: str, index: int) -> dict[str, object]:
    positive = index == 0
    return {
        "symbol": symbol,
        "trade_date": "2026-01-02",
        "available_date": "2026-01-02",
        "source": "derived_price_volume_cmf_obv_v1",
        "source_fetched_at": "2026-01-05T17:30:00+08:00",
        "flow_proxy_kind": "price_volume_cmf_obv",
        "flow_proxy_window": 20,
        "price_volume_flow_signal": 0.2 if positive else -0.2,
        "price_volume_outflow_days": 0 if positive else 2,
        "cmf": 0.2 if positive else -0.2,
        "obv_momentum": 0.2 if positive else -0.2,
        "main_net_inflow": None,
        "main_outflow_days": None,
        "margin_financing_positive": None,
    }
