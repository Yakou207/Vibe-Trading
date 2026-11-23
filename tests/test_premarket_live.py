from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fintech_quant.information.premarket_live import (
    SHANGHAI,
    PremarketLive,
    auction_quote,
    merge_live_market_pulse,
    notice_alert,
    parse_overseas,
    segment,
)

SIGNAL = "2026-11-20"
MONDAY = (2026, 11, 23)
POLICY = {"commission_rate": 0.0003, "minimum_commission": 5.0}


def at(hour: int, minute: int, day: tuple[int, int, int] = MONDAY) -> datetime:
    return datetime(*day, hour, minute, tzinfo=SHANGHAI)


def quote(price: float, previous: float, open_: float, stamp: str, amount_wan: float) -> list[str]:
    fields = ["0"] * 50
    fields[3], fields[4], fields[5] = str(price), str(previous), str(open_)
    fields[30], fields[37] = stamp, str(amount_wan)
    fields[47], fields[48] = str(round(previous * 1.1, 2)), str(round(previous * 0.9, 2))
    return fields


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class Fetchers(dict):
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.tencent_stamp = "20261123092503"
        super().__init__(sina=self._sina, tencent=self._tencent, notices=self._notices)

    def _sina(self, codes):
        self.calls.append("sina")
        return {"gb_$ixic": ["纳斯达克", "22617.7", "-5.28", "2026-11-21 06:30:00"]}

    def _tencent(self, codes):
        self.calls.append("tencent")
        stamp = self.tencent_stamp
        return {
            "sh600001": quote(10.30, 10.00, 10.50, stamp, 2000.0),  # 20m auction turnover
            "sh000300": quote(4010.0, 4000.0, 4020.0, stamp, 0.0),
        }

    def _notices(self, code, begin, end):
        self.calls.append(f"notices {code}")
        return [
            {"公告日期": "2026-11-20", "公告标题": "关于控股股东减持股份的预披露公告"},
            {"公告日期": "2026-11-21", "公告标题": "关于回购股份的进展公告"},
            {"公告日期": "2026-11-10", "公告标题": "关于收到问询函的公告"},
        ]


def inputs() -> dict[str, object]:
    brief = {
        "signal_date": SIGNAL,
        "capital": 100_000.0,
        "policy": POLICY,
        "targets": [{"symbol": "600001.SH", "name": "甲", "category": "target", "target_weight": 0.08}],
        "near_miss": [],
    }
    return {
        "signal_date": SIGNAL,
        "brief": brief,
        "names": {"600001.SH": "甲"},
        "notice_symbols": ["600001.SH"],
        "auction_symbols": ["600001.SH"],
        "luk_setup": {"600001.SH": {"state": "trigger", "stop_price": 9.9, "stop_pct": 0.02}},
        "avg_turnover_20d": {"600001.SH": 100_000_000.0},
    }


def test_segments_split_the_morning_at_0600_and_0925() -> None:
    assert segment(at(5, 59)) == "night"
    assert segment(at(6, 0)) == "pre_open"
    assert segment(at(9, 24)) == "pre_open"
    assert segment(at(9, 25)) == "open"


def test_auction_quote_uses_the_auction_only_between_0925_and_0930() -> None:
    fields = quote(10.3, 10.0, 10.5, "20261123092503", 2000.0)
    assert auction_quote(fields, at(9, 20)) is None
    live = auction_quote(fields, at(9, 27))
    assert live["mode"] == "auction" and live["price"] == 10.3 and live["auction_turnover"] == 20_000_000.0
    late = auction_quote(quote(10.8, 10.0, 10.5, "20261123100000", 90000.0), at(10, 0))
    assert late["mode"] == "open_fallback" and late["price"] == 10.5 and late["auction_turnover"] is None
    assert auction_quote(quote(10.3, 10.0, 10.5, "20261120150000", 1.0), at(9, 27)) is None  # no session
    assert auction_quote(quote(10.3, 10.0, 10.5, "20261123092000", 1.0), at(9, 25)) is None  # not matched yet


def test_overseas_and_notices_are_not_carried_from_the_evening_into_the_morning(tmp_path: Path) -> None:
    fetch, clock = Fetchers(), Clock(at(23, 0, (2026, 11, 22)))
    live = PremarketLive(tmp_path, fetch, clock)

    evening = live.snapshot(inputs(), wait=True)
    assert evening["overseas"]["items"][0]["symbol"] == "NDX"
    clock.now = at(23, 5, (2026, 11, 22))
    live.snapshot(inputs(), wait=True)
    assert fetch.calls.count("sina") == 1  # night cache: ten minutes

    clock.now = at(6, 30)
    live.snapshot(inputs(), wait=True)
    clock.now = at(9, 0)
    live.snapshot(inputs(), wait=True)
    assert fetch.calls.count("sina") == 2  # fetched again after 06:00, then kept
    clock.now = at(9, 1)
    live.snapshot(inputs(), refresh=True, wait=True)
    assert fetch.calls.count("sina") == 3  # manual refresh


def test_notice_alerts_only_flag_negative_overnight_titles(tmp_path: Path) -> None:
    live = PremarketLive(tmp_path, Fetchers(), Clock(at(8, 0)))

    notices = live.snapshot(inputs(), wait=True)["notices"]

    assert notices["status"] == "ok"
    assert [(a["kind"], a["severity"], a["date"]) for a in notices["alerts"]] == [
        ("overnight_negative", "high", "2026-11-20")
    ]
    assert notice_alert("600001.SH", "甲", {"公告标题": "2026年第三季度报告"}) is None


def test_auction_is_captured_in_the_window_and_then_locked_for_the_day(tmp_path: Path) -> None:
    fetch, clock = Fetchers(), Clock(at(9, 27))
    live = PremarketLive(tmp_path, fetch, clock)

    auction = live.snapshot(inputs(), wait=True)["auction"]

    check = auction["checks"][0]
    assert auction["mode"] == "auction" and auction["benchmark_gap_pct"] == 0.0025
    assert check["gap_pct"] == 0.03 and check["auction_volume_ratio"] == 0.2
    assert check["relative_gap_pct"] == 0.0275
    assert "auction_volume_surge" in check["flags"] and "suggested_at_auction" in check
    assert (tmp_path / "2026-11-23" / "auction_live.json").exists()

    restarted = PremarketLive(tmp_path, fetch, Clock(at(10, 30)))
    assert restarted.snapshot(inputs(), wait=True)["auction"]["checks"][0]["auction_price"] == 10.3
    assert fetch.calls.count("tencent") == 1


def test_after_0930_the_open_price_is_used_and_the_volume_ratio_is_left_empty(tmp_path: Path) -> None:
    fetch = Fetchers()
    fetch.tencent_stamp = "20261123100000"
    live = PremarketLive(tmp_path, fetch, Clock(at(10, 0)))

    auction = live.snapshot(inputs(), wait=True)["auction"]

    check = auction["checks"][0]
    assert auction["mode"] == "open_fallback"
    assert check["auction_price"] == 10.5 and check["gap_pct"] == 0.05
    assert "auction_volume_ratio" not in check
    assert auction["benchmark_gap_pct"] == 0.005


def test_parse_overseas_reads_futures_index_and_fx_lines() -> None:
    rows = parse_overseas({
        "hf_CHA50CFD": "12515.3,,12515,12518,12669,12500,05:14:59,12623,12623,1019690,1,1,2026-11-21,A50,1".split(","),
        "fx_susdcnh": "05:59:59,6.6737,6.6757,6.6737,258,6.693,6.6942,6.6684,6.6737,CNH,-0.29,-0.0197,0.0039,,7,6,,2026-11-21".split(","),
    })
    assert [(r["symbol"], round(r["change_pct"], 4)) for r in rows] == [("FTSE.A50", -0.0085), ("USDCNH", -0.0029)]


def test_a_day_without_an_auction_is_retried_at_most_once_a_minute(tmp_path: Path) -> None:
    fetch = Fetchers()
    fetch.tencent_stamp = "20261120150000"  # Sunday: the latest quote is Friday's
    clock = Clock(at(17, 0, (2026, 11, 22)))
    live = PremarketLive(tmp_path, fetch, clock)

    first = live.snapshot(inputs(), wait=True)
    clock.now = at(17, 0, (2026, 11, 22)).replace(second=30)
    again = live.snapshot(inputs())

    assert first["auction"] is None and again["refreshing"] is False
    assert fetch.calls.count("tencent") == 1


def _pulse_brief() -> dict[str, object]:
    return {
        "signal_date": SIGNAL,
        "capital": 100_000.0,
        "policy": POLICY,
        "targets": [{"symbol": "600001.SH", "name": "甲", "category": "target", "target_weight": 0.08}],
        "near_miss": [],
        "market_pulse": {
            "status": "ok",
            "as_of": SIGNAL,
            "regime": "risk_on",
            "regime_note": "沪深300 MA20 上方 · MA50 上方；上涨 3200 / 下跌 1800",
            "indices": [
                {
                    "symbol": "000001.SH",
                    "name": "上证指数",
                    "close": 3350.0,
                    "change_pct": 0.005,
                    "sparkline": [3300.0 + i for i in range(20)],
                    "above_ma20": True,
                    "above_ma50": True,
                    "above_ma250": True,
                    "ma20": 3320.0,
                    "ma50": 3280.0,
                    "ma250": 3150.0,
                },
                {
                    "symbol": "000300.SH",
                    "name": "沪深300",
                    "close": 4000.0,
                    "change_pct": 0.004,
                    "sparkline": [3980.0, 3990.0, 4000.0],
                    "above_ma20": True,
                    "above_ma50": True,
                    "above_ma250": True,
                    "ma20": 3980.0,
                    "ma50": 3960.0,
                    "ma250": 3800.0,
                },
            ],
            "breadth": {
                "advancers": 3200,
                "decliners": 1800,
                "unchanged": 150,
                "limit_up_count": 65,
                "limit_down_count": 5,
                "turnover_cny_bn": 1400.0,
                "turnover_vs_5d_pct": 0.12,
                "csi300_above_ma20_pct": 0.68,
                "csi300_above_ma50_pct": 0.61,
                "csi300_above_ma250_pct": 0.72,
            },
            "overseas": [],
        },
    }


def _pulse_tencent(stamp: str, *, csi300_price: float = 4060.0, sse_price: float = 3390.0) -> dict[str, list[str]]:
    return {
        "sh000001": quote(sse_price, 3350.0, 3360.0, stamp, 4.5e7),
        "sz399001": quote(10850.0, 10750.0, 10780.0, stamp, 5.5e7),
        "sz399006": quote(2280.0, 2240.0, 2250.0, stamp, 2.0e7),
        "sh000300": quote(csi300_price, 4000.0, 4010.0, stamp, 3.0e7),
        "sh000905": quote(5980.0, 5920.0, 5930.0, stamp, 2.5e7),
        "sh000688": quote(1035.0, 1015.0, 1020.0, stamp, 1.2e7),
        "sz399106": quote(2100.0, 2080.0, 2085.0, stamp, 6.5e7),
    }


def _pulse_activity(day_stamp: str, *, adv: int = 3650, dec: int = 1350) -> list[dict[str, object]]:
    return [
        {"item": "上涨", "value": float(adv)},
        {"item": "下跌", "value": float(dec)},
        {"item": "平盘", "value": 120.0},
        {"item": "涨停", "value": 82.0},
        {"item": "跌停", "value": 3.0},
        {"item": "统计日期", "value": day_stamp},
    ]


def test_live_market_pulse_overlays_intraday_and_today_close_with_ttls(tmp_path: Path) -> None:
    calls: list[str] = []
    state = {"stamp": "20261123103205", "csi300": 4060.0, "adv": 3650, "dec": 1350}

    def fake_tencent(codes):
        calls.append("tencent")
        return _pulse_tencent(state["stamp"], csi300_price=state["csi300"])

    def fake_activity():
        calls.append("activity")
        return _pulse_activity(f"2026-11-23 {state['stamp'][8:10]}:{state['stamp'][10:12]}:00",
                               adv=state["adv"], dec=state["dec"])

    def fake_sina(codes):
        calls.append("sina")
        return {"gb_$ixic": ["纳斯达克", "22617.7", "1.25", "2026-11-21 06:30:00"]}

    def fake_notices(code, begin, end):
        calls.append(f"notices:{code}")
        return [{"公告日期": "2026-11-20", "公告标题": "关于控股股东减持股份的预披露公告"}]

    clock = Clock(at(10, 32))
    live = PremarketLive(
        tmp_path,
        {"tencent": fake_tencent, "activity": fake_activity, "sina": fake_sina, "notices": fake_notices},
        clock,
    )
    inp = {**inputs(), "brief": _pulse_brief()}

    # Phase fast skips slow notices and returns live intraday pulse immediately
    snap = live.snapshot(inp, phase="fast")
    assert snap["notices_pending"] is True
    assert not any(c.startswith("notices:") for c in calls)
    assert snap["market_pulse"]["live_status"] == "intraday_live"
    assert snap["market_pulse"]["live_as_of"] == "10:32"
    assert snap["market_pulse"]["live_date"] == "2026-11-23"
    assert len(snap["market_pulse"]["indices"]) == 6
    assert snap["market_pulse"]["turnover_cny_bn"] == 1100.0  # (4.5e7 + 6.5e7) 万元

    merged = merge_live_market_pulse(inp["brief"]["market_pulse"], snap["market_pulse"], signal_date=SIGNAL)
    assert merged["live_status"] == "intraday_live"
    assert merged["live_as_of"] == "10:32"
    assert merged["live_date"] == "2026-11-23"
    sse = next(i for i in merged["indices"] if i["symbol"] == "000001.SH")
    assert sse["close"] == 3390.0 and len(sse["sparkline"]) == 20 and sse["sparkline"][-1] == 3390.0
    csi = next(i for i in merged["indices"] if i["symbol"] == "000300.SH")
    assert csi["close"] == 4060.0 and csi["sparkline"] == [3980.0, 3990.0, 4000.0, 4060.0]
    assert merged["breadth"]["advancers"] == 3650
    assert merged["breadth"]["turnover_cny_bn"] == 1100.0
    assert "turnover_vs_5d_pct" not in merged["breadth"]
    assert merged["breadth"]["csi300_above_ma20_pct"] == 0.68  # preserved from post-close brief
    # Original brief was never mutated in place
    assert inp["brief"]["market_pulse"]["indices"][1]["close"] == 4000.0
    assert len(inp["brief"]["market_pulse"]["indices"][1]["sparkline"]) == 3

    # Within 60s intraday TTL: no refetch
    prev_activity_calls = calls.count("activity")
    clock.now = at(10, 32).replace(second=45)
    live.snapshot(inp, phase="fast")
    assert calls.count("activity") == prev_activity_calls

    # Manual refresh bypasses 60s TTL
    live.snapshot(inp, refresh=True, phase="fast")
    assert calls.count("activity") == prev_activity_calls + 1

    # Crossing into 15:05+ refreshes to capture today_close_live with 600s TTL
    state["stamp"] = "20261123150003"
    clock.now = at(15, 10)
    close_snap = live.snapshot(inp, phase="fast")
    assert close_snap["market_pulse"]["live_status"] == "today_close_live"
    assert close_snap["market_pulse"]["live_date"] == "2026-11-23"
    assert close_snap["market_pulse"]["live_as_of"] == "15:00"
    close_calls = calls.count("activity")

    # Within 600s post-close TTL: cached
    clock.now = at(15, 15)
    live.snapshot(inp, phase="fast")
    assert calls.count("activity") == close_calls

    # Phase notices runs slow scan and clears notices_pending
    notice_snap = live.snapshot(inp, phase="notices")
    assert notice_snap["notices_pending"] is False
    assert notice_snap["notices"]["status"] == "ok"
    assert any(c.startswith("notices:") for c in calls)

    # Subsequent fast snapshot sees cached notices -> notices_pending is False
    after_snap = live.snapshot(inp, phase="fast")
    assert after_snap["notices_pending"] is False


def test_preopen_weekend_and_covered_signal_date_do_not_mislabel_as_live(tmp_path: Path) -> None:
    pulse_calls: list[str] = []

    def fake_tencent(codes):
        if "sz399106" in codes:
            pulse_calls.append("tencent_pulse")
        return _pulse_tencent("20261123100000")

    def fake_activity():
        pulse_calls.append("activity")
        return _pulse_activity("2026-11-23 10:00:00")

    fetchers = {
        "sina": lambda codes: {},
        "tencent": fake_tencent,
        "activity": fake_activity,
        "notices": lambda code, b, e: [],
    }
    inp = {**inputs(), "brief": _pulse_brief()}

    # 1. Pre-open (08:30 Monday): no live A-share pulse fetched
    pre = PremarketLive(tmp_path, fetchers, Clock(at(8, 30)))
    snap_pre = pre.snapshot(inp, phase="fast")
    assert snap_pre["market_pulse"] is None
    assert pulse_calls == []
    merged_pre = merge_live_market_pulse(inp["brief"]["market_pulse"], snap_pre["market_pulse"], signal_date=SIGNAL)
    assert merged_pre["live_status"] == "post_close"
    assert merged_pre["indices"][0]["close"] == 3350.0

    # 2. Weekend (Sunday 11:00): no live A-share pulse fetched
    wk = PremarketLive(tmp_path, fetchers, Clock(at(11, 0, (2026, 11, 22))))
    snap_wk = wk.snapshot(inp, phase="fast")
    assert snap_wk["market_pulse"] is None
    assert pulse_calls == []

    # 3. Signal date already equals today (today's post-close brief already completed)
    today_inp = {**inp, "signal_date": "2026-11-23"}
    covered = PremarketLive(tmp_path, fetchers, Clock(at(17, 0)))
    snap_cov = covered.snapshot(today_inp, phase="fast")
    assert snap_cov["market_pulse"] is None
    assert pulse_calls == []

    # 4. Weekday holiday where Tencent/Legu only have prior signal_date's quotes -> not mislabeled live
    holiday_fetchers = {
        "sina": lambda codes: {},
        "tencent": lambda codes: _pulse_tencent("20261120150000"),
        "activity": lambda: _pulse_activity("2026-11-20 15:00:00"),
        "notices": lambda code, b, e: [],
    }
    hol = PremarketLive(tmp_path, holiday_fetchers, Clock(at(10, 30)))
    snap_hol = hol.snapshot(inp, phase="fast")
    assert snap_hol["market_pulse"]["live_status"] == "post_close"
    merged_hol = merge_live_market_pulse(inp["brief"]["market_pulse"], snap_hol["market_pulse"], signal_date=SIGNAL)
    assert merged_hol["live_status"] == "post_close"
    assert merged_hol["indices"][0]["close"] == 3350.0


def test_partial_and_full_live_pulse_failures_preserve_brief_and_recompute_regime(tmp_path: Path) -> None:
    brief_pulse = _pulse_brief()["market_pulse"]

    # Case 1: Legu fails while Tencent succeeds -> updates indices + turnover, keeps brief breadth
    def broken_activity():
        raise ConnectionError("legu down")

    live_partial = PremarketLive(
        tmp_path,
        {
            "sina": lambda codes: {},
            "tencent": lambda codes: _pulse_tencent("20261123101500", csi300_price=3900.0, sse_price=3290.0),
            "activity": broken_activity,
            "notices": lambda code, b, e: [],
        },
        Clock(at(10, 15)),
    )
    inp = {**inputs(), "brief": _pulse_brief()}
    snap = live_partial.snapshot(inp, phase="fast")
    assert snap["market_pulse"]["status"] == "partial"
    merged = merge_live_market_pulse(brief_pulse, snap["market_pulse"], signal_date=SIGNAL)
    assert merged["live_status"] == "intraday_live"
    assert merged["breadth"]["advancers"] == 3200  # preserved from brief when Legu failed
    assert merged["breadth"]["turnover_cny_bn"] == 1100.0  # updated from Tencent
    assert merged["breadth"]["csi300_above_ma20_pct"] == 0.68
    csi = next(i for i in merged["indices"] if i["symbol"] == "000300.SH")
    assert csi["close"] == 3900.0
    assert csi["above_ma20"] is False and csi["above_ma50"] is False  # recomputed from ma20=3980, ma50=3960
    assert merged["regime"] == "neutral"  # dropped from risk_on since below MA20/50 while brief adv>dec

    # Case 2: Both Tencent and Legu succeed with bearish move -> regime flips risk_on -> risk_off
    live_bear = PremarketLive(
        tmp_path,
        {
            "sina": lambda codes: {},
            "tencent": lambda codes: _pulse_tencent("20261123102000", csi300_price=3900.0, sse_price=3250.0),
            "activity": lambda: _pulse_activity("2026-11-23 10:20:00", adv=1100, dec=3900),
            "notices": lambda code, b, e: [],
        },
        Clock(at(10, 20)),
    )
    bear_merged = merge_live_market_pulse(
        brief_pulse, live_bear.snapshot(inp, phase="fast")["market_pulse"], signal_date=SIGNAL
    )
    assert bear_merged["regime"] == "risk_off"
    assert "上涨 1100 / 下跌 3900" in bear_merged["regime_note"]

    # Case 3: Both Tencent and Legu fail -> brief market_pulse returned completely untouched
    def broken_tencent(codes):
        raise TimeoutError("tencent down")

    live_dead = PremarketLive(
        tmp_path,
        {"sina": lambda codes: {}, "tencent": broken_tencent, "activity": broken_activity, "notices": lambda c, b, e: []},
        Clock(at(10, 25)),
    )
    dead_snap = live_dead.snapshot(inp, phase="fast")
    fallback = merge_live_market_pulse(brief_pulse, dead_snap["market_pulse"], signal_date=SIGNAL)
    assert fallback["live_status"] == "post_close"
    assert fallback["regime"] == "risk_on"
    assert fallback["indices"][1]["close"] == 4000.0
    assert fallback["breadth"]["advancers"] == 3200
    assert fallback["breadth"]["turnover_cny_bn"] == 1400.0
