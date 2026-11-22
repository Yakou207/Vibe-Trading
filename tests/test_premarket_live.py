from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fintech_quant.information.premarket_live import (
    SHANGHAI,
    PremarketLive,
    auction_quote,
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
