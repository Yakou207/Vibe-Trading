from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from fintech_quant.reports.live_stock import LiveContext, live_bars, reference_momentum, resolve_any
from fintech_quant.reports.picker import stock_payload, universe_payload
from fintech_quant.research.momentum_setup import SymbolSeries
from test_momentum_setup import _leader_with_flush
from test_picker_payload import _data


TODAY = date(2026, 10, 20)


class Counting:
    def __init__(self, fn):
        self.fn, self.calls = fn, 0

    def __call__(self, **kwargs):
        self.calls += 1
        return self.fn(**kwargs)


def _sina_rows(**kwargs):
    return [
        {
            "date": b.trade_date,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
        }
        for b in _leader_with_flush().bars
    ]


def _fetchers(**overrides):
    base = {
        "code_name": lambda: [
            {"code": "300624", "name": "万兴 科技"},
            {"code": "920000", "name": "安徽凤凰"},
            {"code": "600001", "name": "领涨股份"},
            {"code": "bad", "name": "invalid row"},
        ],
        "sina": _sina_rows,
        "tencent": lambda **kw: [],
        "value": lambda **kw: [{"数据日期": "2026-10-19", "PE(TTM)": 15.0, "市净率": 2.0}],
        "financials": lambda **kw: [
            {"报告期": "2026-06-30", "净资产收益率": "8.0%", "营业总收入同比增长率": "12.0%"}
        ],
    }
    base.update(overrides)
    return base


def test_all_shares_normalise_exchanges_and_resolve_by_code_or_name(tmp_path: Path) -> None:
    live = LiveContext(cache_dir=tmp_path, fetchers=_fetchers(), today=TODAY)

    shares = live.all_shares()

    assert shares == {"300624.SZ": "万兴科技", "920000.BJ": "安徽凤凰", "600001.SH": "领涨股份"}
    assert resolve_any(live, "300624") == "300624.SZ"
    assert resolve_any(live, "920000.bj") == "920000.BJ"
    assert resolve_any(live, "万兴") == "300624.SZ"
    assert resolve_any(live, "不存在") is None


def test_history_falls_back_to_tencent_and_converts_lots_to_shares(tmp_path: Path) -> None:
    def broken(**kwargs):
        raise ConnectionError("sina down")

    tencent = [
        {
            "date": "2026-10-19",
            "open": 10.0,
            "high": 10.5,
            "low": 9.8,
            "close": 10.2,
            "amount": 1234.0,
        }
    ]
    live = LiveContext(
        cache_dir=tmp_path,
        fetchers=_fetchers(sina=broken, tencent=lambda **kw: tencent),
        today=TODAY,
    )

    bars, source = live_bars(live, "300624.SZ")

    assert source == "tencent"
    assert bars[0].volume == pytest.approx(123400.0)


def test_history_fails_when_both_sources_fail(tmp_path: Path) -> None:
    live = LiveContext(
        cache_dir=tmp_path,
        fetchers=_fetchers(sina=lambda **kw: [], tencent=lambda **kw: []),
        today=TODAY,
    )

    with pytest.raises(ValueError, match="no price history"):
        live_bars(live, "300624.SZ")


def test_reference_momentum_ranks_against_csi300_cross_section() -> None:
    item = SymbolSeries("300624.SZ", _leader_with_flush().bars)
    reference = {f"S{i}": {"r21": i / 100, "r63": i / 100, "r126": i / 100} for i in range(-50, 50)}

    momentum = reference_momentum(item, reference)

    own = item.bars[-1].close / item.bars[-22].close - 1
    expected = sum(1 for i in range(-50, 50) if i / 100 < own) / 100
    assert momentum["r21"] == pytest.approx(own)
    assert momentum["r21_pct"] == pytest.approx(expected)


def test_non_member_search_returns_labelled_live_analysis_and_caches(tmp_path: Path) -> None:
    data = _data()
    sina = Counting(_sina_rows)
    live = LiveContext(cache_dir=tmp_path, fetchers=_fetchers(sina=sina), today=TODAY)

    payload = stock_payload(data, "万兴科技", live)
    again = stock_payload(data, "300624", live)

    assert payload["mode"] == "live" and payload["symbol"] == "300624.SZ"
    assert payload["price_scale"] == "qfq" and payload["price_source"] == "sina"
    assert payload["analysis"]["state"] in {
        "trigger",
        "setup",
        "leader_weak_base",
        "leader_no_base",
        "avoid",
    }
    assert payload["baseline"]["total"] > 0
    assert payload["fundamentals"]["roe"] == pytest.approx(0.16)
    assert payload["verdict"]["notes"][0].startswith("非沪深 300 成分")
    assert again["analysis"] == payload["analysis"]
    assert sina.calls == 1


def test_members_keep_point_in_time_path_and_unknown_names_error(tmp_path: Path) -> None:
    data = _data()
    live = LiveContext(cache_dir=tmp_path, fetchers=_fetchers(), today=TODAY)

    assert stock_payload(data, "600001", live)["mode"] == "csi300"
    assert "A 股" in stock_payload(data, "不存在", live)["error"]
    universe = universe_payload(data, live)
    assert {"symbol": "600001.SH", "name": "领涨股份", "csi300": True} in universe
    assert len(universe) == 3
