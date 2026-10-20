from __future__ import annotations

import threading
from datetime import date
from pathlib import Path

import pytest

from fintech_quant.reports.live_stock import (
    LiveContext,
    intraday_payload,
    live_bars,
    live_intraday,
    reference_momentum,
    resolve_any,
)
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


def _em_minutes(**kwargs):
    return [  # two sessions, as Eastmoney returns several days; volume in lots
        {"时间": "2026-10-19 15:00:00", "收盘": 9.9, "成交量": 50, "均价": 9.85},
        {"时间": "2026-10-20 09:31:00", "收盘": 10.0, "成交量": 10, "均价": 10.0},
        {"时间": "2026-10-20 09:32:00", "收盘": 10.2, "成交量": 30, "均价": 10.12},
    ]


def _sina_minutes(**kwargs):
    return [  # strings, volume in shares, no 均价
        {"day": "2026-10-19 15:00:00", "close": "9.90", "volume": "5000", "amount": "49500"},
        {"day": "2026-10-20 09:31:00", "close": "10.00", "volume": "1000", "amount": "10000"},
        {"day": "2026-10-20 09:32:00", "close": "10.20", "volume": "3000", "amount": "30600"},
    ]


def _down(**kwargs):
    raise ConnectionError("proxy closed the connection")


def test_intraday_uses_eastmoney_latest_session_without_writing_anything(tmp_path: Path) -> None:
    seen = {}

    def em(**kwargs):
        seen.update(kwargs)
        return _em_minutes()

    sina = Counting(_sina_minutes)
    live = LiveContext(
        cache_dir=tmp_path, fetchers=_fetchers(minute_em=em, minute_sina=sina), today=TODAY
    )

    payload = intraday_payload(live, "万兴科技")

    assert seen == {"symbol": "300624"}
    assert sina.calls == 0
    assert payload["symbol"] == "300624.SZ" and payload["name"] == "万兴科技"
    assert payload["source"] == "minute_em" and payload["date"] == "2026-10-20"
    assert payload["prev_close"] == pytest.approx(9.9)
    assert payload["points"] == [
        {"time": "2026-10-20 09:31", "price": 10.0, "volume": 1000.0, "avg": 10.0},
        {"time": "2026-10-20 09:32", "price": 10.2, "volume": 3000.0, "avg": 10.12},
    ]
    assert sorted(p.name for p in tmp_path.rglob("*.json")) == ["all_shares.json"]


def test_intraday_falls_back_to_sina_and_derives_the_average_price(tmp_path: Path) -> None:
    seen = {}

    def sina(**kwargs):
        seen.update(kwargs)
        return _sina_minutes()

    live = LiveContext(
        cache_dir=tmp_path, fetchers=_fetchers(minute_em=_down, minute_sina=sina), today=TODAY
    )

    payload = live_intraday(live, "600001.SH")

    assert seen == {"symbol": "sh600001"}
    assert payload["source"] == "minute_sina" and payload["date"] == "2026-10-20"
    assert payload["prev_close"] == pytest.approx(9.9)
    assert [p["avg"] for p in payload["points"]] == pytest.approx([10.0, 40600 / 4000])
    assert [p["volume"] for p in payload["points"]] == [1000.0, 3000.0]


def test_intraday_times_out_a_hung_primary_and_falls_back(tmp_path: Path) -> None:
    release = threading.Event()

    def hung(**kwargs):
        release.wait(5)
        return _em_minutes()

    live = LiveContext(
        cache_dir=tmp_path,
        fetchers=_fetchers(minute_em=hung, minute_sina=_sina_minutes),
        today=TODAY,
    )
    try:
        payload = live_intraday(live, "600001.SH", timeout=0.05)
    finally:
        release.set()

    assert payload["source"] == "minute_sina"


def test_intraday_reports_an_error_when_both_sources_fail(tmp_path: Path) -> None:
    live = LiveContext(
        cache_dir=tmp_path,
        fetchers=_fetchers(minute_em=_down, minute_sina=lambda **kw: []),
        today=TODAY,
    )

    with pytest.raises(ValueError, match="no intraday data"):
        live_intraday(live, "600001.SH")
    payload = intraday_payload(live, "600001")
    assert payload == {"error": payload["error"]}
    assert "minute_em: ConnectionError" in payload["error"]
    assert "minute_sina: empty" in payload["error"]
    assert "未找到" in intraday_payload(live, "不存在")["error"]


def test_intraday_still_resolves_a_full_code_when_the_share_list_is_down(tmp_path: Path) -> None:
    live = LiveContext(
        cache_dir=None,
        fetchers=_fetchers(code_name=_down, minute_em=_em_minutes),
        today=TODAY,
    )

    payload = intraday_payload(live, "600001.SH")

    assert payload["symbol"] == "600001.SH" and payload["name"] == ""
    assert "error" in intraday_payload(live, "领涨股份")
