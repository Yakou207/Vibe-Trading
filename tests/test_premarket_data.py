from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from fintech_quant.information.premarket_data import (
    build_market_pulse,
    build_pitfall_calendar,
    disclosure_periods,
    next_weekday,
)

SIGNAL = date(2026, 11, 20)  # a Friday


def _bars(end: date, n: int, last: float, rising: bool) -> list[dict[str, object]]:
    rows, day, value = [], end, last
    while len(rows) < n:
        if day.weekday() < 5:
            rows.append({"date": day.isoformat(), "close": value})
            value = value - 1 if rising else value + 1
        day -= timedelta(days=1)
    return list(reversed(rows))


def _tencent(day: date, amount_wan: float) -> list[str]:
    fields = ["0"] * 50
    fields[30] = day.strftime("%Y%m%d") + "161400"
    fields[37] = str(amount_wan)
    return fields


def _fetchers(activity_day: date = SIGNAL) -> dict[str, object]:
    return {
        "index_daily": lambda code: _bars(SIGNAL, 260, 3000.0, rising=code != "sh000688"),
        "activity": lambda: [
            {"item": "上涨", "value": 3000.0}, {"item": "下跌", "value": 2000.0},
            {"item": "平盘", "value": 100.0}, {"item": "涨停", "value": 50.0},
            {"item": "跌停", "value": 5.0}, {"item": "统计日期", "value": f"{activity_day} 15:00:00"},
        ],
        "tencent": lambda codes: {"sh000001": _tencent(SIGNAL, 6e7), "sz399106": _tencent(SIGNAL, 9e7)},
    }


def _prices(tmp_path: Path) -> Path:
    path = tmp_path / "daily.csv"
    lines = ["symbol,trade_date,close"]
    for row in _bars(SIGNAL, 260, 100.0, rising=True):
        lines.append(f"600001.SH,{row['date']},{row['close']}")
    for row in _bars(SIGNAL, 260, 100.0, rising=False):
        lines.append(f"600002.SH,{row['date']},{row['close']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_market_pulse_reads_every_source_for_the_signal_date(tmp_path: Path) -> None:
    history = tmp_path / "turnover.json"
    history.write_text(json.dumps({f"2026-11-{d}": 1000.0 for d in (13, 16, 17, 18, 19)}))

    pulse = build_market_pulse(SIGNAL, _prices(tmp_path), ["600001.SH", "600002.SH"], history, _fetchers())

    assert pulse["status"] == "ok" and pulse["missing"] == []
    assert [i["symbol"] for i in pulse["indices"]][:2] == ["000001.SH", "399001.SZ"]
    csi300 = next(i for i in pulse["indices"] if i["symbol"] == "000300.SH")
    assert csi300["close"] == 3000.0 and len(csi300["sparkline"]) == 20
    assert csi300["above_ma20"] and csi300["above_ma250"]
    assert csi300["ma20"] is not None and csi300["ma50"] is not None and csi300["ma250"] is not None
    assert csi300["close"] > csi300["ma20"]
    star50 = next(i for i in pulse["indices"] if i["symbol"] == "000688.SH")
    assert star50["above_ma20"] is False
    assert star50["ma20"] is not None and star50["close"] < star50["ma20"]
    breadth = pulse["breadth"]
    assert (breadth["advancers"], breadth["decliners"], breadth["limit_up_count"]) == (3000, 2000, 50)
    assert breadth["turnover_cny_bn"] == 1500.0  # (6e7 + 9e7) 万元
    assert breadth["turnover_vs_5d_pct"] == 0.5
    assert breadth["csi300_above_ma20_pct"] == 0.5
    assert pulse["regime"] == "risk_on"
    assert json.loads(history.read_text())["2026-11-20"] == 1500.0


def test_market_pulse_drops_another_days_data_instead_of_showing_it(tmp_path: Path) -> None:
    fetchers = _fetchers(activity_day=SIGNAL - timedelta(days=1))
    fetchers["tencent"] = lambda codes: {c: _tencent(SIGNAL + timedelta(days=3), 1.0) for c in codes}

    pulse = build_market_pulse(SIGNAL, _prices(tmp_path), ["600001.SH"], tmp_path / "t.json", fetchers)

    assert pulse["status"] == "partial"
    assert "advancers" not in pulse["breadth"] and "turnover_cny_bn" not in pulse["breadth"]
    assert any(m.startswith("activity") for m in pulse["missing"])
    assert any(m.startswith("turnover") for m in pulse["missing"])
    assert pulse["regime"] == "unknown"
    assert not (tmp_path / "t.json").exists()


def test_pitfall_calendar_covers_actions_unlocks_and_suspensions(tmp_path: Path) -> None:
    raw = tmp_path / "corporate_actions"
    raw.mkdir()
    (raw / "600001.SH.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
        {"_action_type": "distribution", "进度": "实施", "除权除息日": "2026-11-23", "派息": 3.0, "送股": 0, "转增": 0},
        {"_action_type": "distribution", "进度": "预案", "除权除息日": "2026-11-24", "派息": 9.0},
        {"_action_type": "distribution", "进度": "实施", "除权除息日": "2026-06-01", "派息": 1.0},
        {"_action_type": "rights_issue", "除权基准日": "2026-11-26", "配股比例": 3, "配股价格": 5.2},
    ]), encoding="utf-8")
    (raw / "999999.SH.jsonl").write_text(json.dumps({"进度": "实施", "除权除息日": "2026-11-23"}), encoding="utf-8")
    names = {"600001.SH": "甲", "000002.SZ": "乙", "300003.SZ": "丙"}
    fetchers = {
        "unlock": lambda start, end: [
            {"股票代码": "000002", "解禁时间": "2026-11-25", "限售股类型": "首发原股东限售股份",
             "实际解禁数量": 5e7, "占解禁前流通市值比例": 0.08},
            {"股票代码": "688888", "解禁时间": "2026-11-25", "占解禁前流通市值比例": 0.5},
        ],
        "suspensions": lambda day: [{"代码": "300003", "停牌时间": "2026-11-23", "停牌原因": "刊登重要公告",
                                    "停牌期限": "停牌一天", "预计复牌时间": "2026-11-24"}],
        "earnings": lambda period: pytest.fail("no disclosure season in late November"),
    }

    calendar = build_pitfall_calendar(SIGNAL, names, raw, fetchers)

    assert calendar["status"] == "ok"
    kinds = [(a["symbol"], a["kind"], a["severity"], a["date"]) for a in calendar["alerts"]]
    assert kinds == [  # severity first, then date
        ("300003.SZ", "suspension", "high", "2026-11-23"),
        ("000002.SZ", "unlock", "high", "2026-11-25"),
        ("600001.SH", "ex_dividend", "medium", "2026-11-23"),  # Monday is the next session
        ("600001.SH", "ex_dividend", "info", "2026-11-26"),
    ]
    assert calendar["alerts"][2]["title"] == "除权除息：每 10 股派 3 元"
    assert "配股价 5.2" in calendar["alerts"][3]["title"]


def test_pitfall_calendar_marks_a_failed_source_partial(tmp_path: Path) -> None:
    def broken(*args: object) -> object:
        raise ConnectionError("proxy closed")

    calendar = build_pitfall_calendar(
        SIGNAL, {"600001.SH": "甲"}, tmp_path, {"unlock": broken, "suspensions": lambda day: [], "earnings": broken}
    )

    assert calendar["status"] == "partial"
    assert calendar["missing"] == ["unlock: ConnectionError: proxy closed"]


def test_disclosure_periods_and_next_session() -> None:
    assert disclosure_periods(date(2026, 11, 23)) == []
    assert disclosure_periods(date(2026, 10, 20)) == ["20260930"]
    assert disclosure_periods(date(2027, 4, 10)) == ["20261231", "20270331"]
    assert next_weekday(SIGNAL) == date(2026, 11, 23)
