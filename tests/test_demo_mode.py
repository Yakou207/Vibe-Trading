from __future__ import annotations

import json
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from fintech_quant.reports.demo_fixtures import (
    DEMO_AS_OF,
    DEMO_STOCKS,
    build_demo_workspace,
    demo_jev_payload,
    demo_research_payload,
)
from fintech_quant.reports.desk import build_desk_snapshot
from fintech_quant.reports.picker import load_picker_data, picks_payload, stock_payload
from scripts.build_demo_pages import build_demo_pages


ROOT = Path(__file__).resolve().parents[1]
REAL_COMPANY_BLOCKLIST = {
    "宁德时代",
    "紫金矿业",
    "比亚迪",
    "美的集团",
    "长江电力",
    "招商银行",
    "中国平安",
    "贵州茅台",
    "恒瑞医药",
    "五粮液",
}
BROKER_RATING_TERMS = ("买入", "增持", "强烈推荐", "推荐评级")


def test_demo_stocks_are_strictly_fictional_and_have_no_broker_ratings(tmp_path: Path) -> None:
    for spec in DEMO_STOCKS:
        symbol = str(spec["symbol"])
        name = str(spec["name"])
        assert re.fullmatch(r"999\d{3}\.SH", symbol), f"non-fictional demo symbol: {symbol}"
        assert name not in REAL_COMPANY_BLOCKLIST

    demo = build_demo_workspace(tmp_path)
    picker = load_picker_data(demo.state)
    for spec in DEMO_STOCKS:
        research = demo_research_payload(picker, str(spec["symbol"]))
        blob = json.dumps(research, ensure_ascii=False)
        for term in BROKER_RATING_TERMS:
            assert term not in blob, f"unexpected broker rating term {term!r} in demo research"
        for item in research["items"]:
            assert not item.get("rating")


def test_demo_workspace_passes_hash_verified_desk_and_picker_loaders(tmp_path: Path) -> None:
    demo = build_demo_workspace(tmp_path)

    snapshot = build_desk_snapshot(demo.cycle_root, pnl_curve=demo.pnl_curve, quotes_status="demo")
    assert snapshot["as_of"] == DEMO_AS_OF
    assert snapshot["quotes_status"] == "demo"
    assert len(snapshot["agents"]) >= 6
    assert snapshot["backtest_curve"] is not None
    curve = snapshot["backtest_curve"]["series"]
    # Endpoints must match the withdrawn-leak rerun (docs/research/2026-10-29-lag-fix-rerun.md).
    assert curve["risk_controlled"]["equity"][-1] == 83000.0
    assert curve["baseline"]["equity"][-1] == 65600.0
    assert snapshot["header"]["excess_return"] is None
    assert snapshot["header"]["paper_return"] <= snapshot["header"]["benchmark_return"]

    picker = load_picker_data(demo.state)
    assert picker.as_of == DEMO_AS_OF
    assert len(picker.members) == len(DEMO_STOCKS)

    scoring_v2 = json.loads(demo.scoring_v2.read_text(encoding="utf-8"))
    payload = stock_payload(picker, "999001", live=None, scoring_v2=scoring_v2, fresh=False)
    assert payload["symbol"] == "999001.SH"
    assert payload["verdict"]["level"] == "entry"
    assert payload["scoring_v2"]["score"] is not None
    # The picker template reads these six categories; a missing one breaks the stock view.
    assert set(payload["scoring_v2"]["categories"]) == {
        "value", "quality_growth", "low_risk", "liquidity", "reversal", "momentum"
    }

    pool = json.loads((demo.pool_root / "state.json").read_text(encoding="utf-8"))
    pool_v2 = json.loads((demo.pool_v2_root / "state.json").read_text(encoding="utf-8"))
    picks = picks_payload(picker, pool, pool_v2)
    assert len(picks["candidates"]) >= 2
    assert picks["candidates"][0]["symbol"] in {"999001.SH", "999002.SH"}

    research = demo_research_payload(picker, "999001")
    assert research["symbol"] == "999001.SH"
    assert len(research["items"]) >= 1
    assert research["jev_record"]["verdict"] == "support"
    assert demo_jev_payload(picker, "999009")["verdict"] == "veto"


def test_build_demo_pages_writes_self_contained_static_site(tmp_path: Path) -> None:
    written = build_demo_pages(tmp_path)
    names = {path.name for path in written}
    assert names == {"index.html", "picks.html", ".nojekyll"}

    desk_html = (tmp_path / "index.html").read_text(encoding="utf-8")
    picks_html = (tmp_path / "picks.html").read_text(encoding="utf-8")
    assert "__DESK_" not in desk_html
    assert "__PICKER_" not in picks_html
    assert "虚构数据，仅供界面演示，不构成任何投资建议" in desk_html
    assert "Fictional data for UI demo only. Not investment advice." in desk_html
    assert "虚构数据，仅供界面演示，不构成任何投资建议" in picks_html
    assert "static-demo-bundle" in picks_html
    assert "./picks.html" in desk_html
    assert "./index.html" in picks_html


def test_serve_trading_desk_demo_mode_serves_all_endpoints_offline() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])

    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "scripts" / "serve_trading_desk.py"),
            "--demo",
            "--port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        snapshot = json.loads(_get(f"http://127.0.0.1:{port}/api/snapshot"))
        assert snapshot["as_of"] == DEMO_AS_OF
        assert snapshot["quotes_status"] == "demo"

        assert "CSI 300 Desk" in _get(f"http://127.0.0.1:{port}/")
        assert "选股 · CSI 300" in _get(f"http://127.0.0.1:{port}/picks")

        stock = json.loads(_get(f"http://127.0.0.1:{port}/api/stock?q=999001"))
        assert stock["verdict"]["level"] == "entry"

        research = json.loads(_get(f"http://127.0.0.1:{port}/api/research?q=999001"))
        assert research["jev_record"]["verdict"] == "support"

        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/jev?q=999001", method="POST")
        with _NO_PROXY_OPENER.open(req, timeout=3) as resp:
            jev = json.loads(resp.read().decode("utf-8"))
        assert jev["verdict"] == "support"
    finally:
        process.terminate()
        process.wait(timeout=5)


_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _get(url: str) -> str:
    deadline = time.monotonic() + 10
    while True:
        try:
            with _NO_PROXY_OPENER.open(url, timeout=2) as response:
                return response.read().decode("utf-8")
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.1)
