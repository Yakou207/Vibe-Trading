from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_validate_research_data_script_writes_failure_report_before_exit(tmp_path: Path) -> None:
    universe = tmp_path / "universe.csv"
    features = tmp_path / "features.csv"
    membership = tmp_path / "membership.csv"
    fundamentals = tmp_path / "fundamentals.csv"
    capital_flow = tmp_path / "capital_flow.csv"
    output = tmp_path / "data_health.json"
    universe.write_text("symbol\n000001\n600000\n", encoding="utf-8")
    features.write_text(
        "symbol,trade_date,open,high,low,close,volume,amount,source,return_1d,ma20,ma60,ma250,"
        "close_above_ma20,close_above_ma60,close_above_ma250,rsi14,macd_line,macd_signal,macd_hist,"
        "macd_positive,volatility20\n"
        "000001,2026-01-02,10,10,10,10,1000,10000,fixture,0.01,9,8,7,true,true,true,55,0.1,0.05,0.05,true,0.02\n",
        encoding="utf-8",
    )
    membership.write_text(
        "index_code,symbol,member_from,member_to,source,source_fetched_at\n"
        "000300,000001.SZ,2025-01-01,,csindex,2026-07-10T12:00:00+08:00\n"
        "000300,600000.SH,2025-01-01,,csindex,2026-07-10T12:00:00+08:00\n",
        encoding="utf-8",
    )
    fundamentals.write_text(
        "symbol,available_date,pe,pb,roe,growth\n"
        "000001,2026-01-01,18,1.5,0.16,0.12\n",
        encoding="utf-8",
    )
    capital_flow.write_text(
        "symbol,trade_date,available_date,main_net_inflow,main_outflow_days,margin_financing_positive\n"
        "000001,2026-01-02,2026-01-02,-100,5,false\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/validate_research_data.py",
            "--features",
            str(features),
            "--universe",
            str(universe),
            "--membership",
            str(membership),
            "--fundamentals",
            str(fundamentals),
            "--capital-flow",
            str(capital_flow),
            "--expected-members",
            "2",
            "--fundamental-warmup-days",
            "0",
            "--output",
            str(output),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert "price_coverage" in {issue["code"] for issue in payload["issues"]}
    assert f"data_health={output}" in completed.stdout
