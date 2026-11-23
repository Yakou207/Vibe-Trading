from __future__ import annotations

import time
from datetime import datetime

import pytest

from fintech_quant.information.headlines import (
    MIN_SCORE,
    SHANGHAI,
    collect_headlines,
    merge_same_story,
    parse_feed,
    pick_headlines,
)

NOW = datetime(2026, 11, 24, 2, 20, tzinfo=SHANGHAI)


def distinct(i: int) -> str:
    """Six CJK characters no other ``distinct(j)`` shares, so the flashes never merge."""
    return "".join(chr(0x4E00 + 6 * i + k) for k in range(6))


def flash(source: str, hhmm: str, title: str, day: str = "2026-11-24") -> dict[str, object]:
    return {"source": source, "published_at": datetime.fromisoformat(f"{day}T{hhmm}:00+08:00"),
            "title": title, "summary": "", "url": ""}


@pytest.fixture
def utc_machine(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_local_zone_feeds_are_converted_to_shanghai(utc_machine) -> None:
    ths = parse_feed("ths", [{"标题": "英伟达涨幅收窄至30%", "内容": "英伟达涨幅收窄至30%。（财联社）",
                              "发布时间": "2026-11-23 17:52:28", "链接": "u"}])
    em = parse_feed("em", [{"标题": "英伟达股价涨幅收窄至30%", "摘要": "", "发布时间": "2026-11-24 01:51:39", "链接": ""}])
    futu = parse_feed("futu", [{"标题": "", "内容": "【据称英伟达董事会绕过高管恢复黄仁勋职务】据知情人士透露……",
                                "发布时间": "2026-11-23 17:57:45", "链接": ""}])
    assert ths[0]["published_at"] == datetime(2026, 11, 24, 1, 52, 28, tzinfo=SHANGHAI)
    assert em[0]["published_at"] == datetime(2026, 11, 24, 1, 51, 39, tzinfo=SHANGHAI)
    assert futu[0]["title"] == "据称英伟达董事会绕过高管恢复黄仁勋职务"


def test_relayed_flash_merges_into_one_story_with_its_feeds() -> None:
    stories = merge_same_story([
        flash("东方财富", "01:51", "英伟达股价涨幅收窄至30%"),
        flash("同花顺", "01:52", "英伟达涨幅收窄至30%"),
        flash("新浪", "01:52", "英伟达涨幅收窄至30%。"),
        flash("富途", "01:57", "据称英伟达董事会绕过高管恢复黄仁勋职务"),
        flash("新浪", "05:30", "英伟达涨幅收窄至30%"),  # same words hours later: a new flash
    ])
    assert [sorted(s["sources"]) for s in stories] == [["东方财富", "同花顺", "新浪"], ["富途"], ["新浪"]]
    assert stories[0]["title"] == "英伟达股价涨幅收窄至30%"  # the longest version


def test_hot_actor_outranks_routine_relayed_flash_and_one_headline_per_topic() -> None:
    pool = [
        flash("东方财富", "02:05", "美国两年期国债中标收益率为4.700%"),
        flash("同花顺", "02:06", "美国两年期国债中标收益率为4.700%"),
        flash("富途", "02:06", "美国两年期国债中标收益率为4.700%"),
        flash("东方财富", "01:51", "英伟达股价涨幅收窄至30%"),
        flash("同花顺", "01:52", "英伟达涨幅收窄至30%"),
        *[flash("富途", f"01:{m:02d}", f"黄仁勋{distinct(m)}") for m in range(10, 30)],
        flash("东方财富", "00:10", "美国财政部长：将继续推进减税"),
        flash("东方财富", "00:20", "美国银行：预计欧洲央行将在明年降息"),
    ]
    headlines = pick_headlines(pool, NOW)
    assert [h["entities"] for h in headlines] == [["英伟达"]]  # routine and foreign items stay out
    top = headlines[0]
    assert top["title"] == "英伟达股价涨幅收窄至30%"
    assert top["sources"] == ["东方财富", "同花顺"]
    assert top["related_count"] == 20 and len(top["related"]) == 8
    assert top["score"] >= MIN_SCORE
    assert {"电子", "计算机", "通信"} <= set(top["sectors"])


def test_old_flashes_fall_out_of_the_pool() -> None:
    pool = [flash("东方财富", f"10:{m:02d}", f"英伟达第{m}条") for m in range(20)]
    assert pick_headlines(pool, NOW) == []  # 2026-11-24 10:xx is in the future
    yesterday = [flash("东方财富", f"10:{m:02d}", f"英伟达第{m}条", day="2026-11-23") for m in range(20)]
    assert pick_headlines(yesterday, NOW) == []  # more than 12 hours old


def _feeds(quotes):
    em = [{"标题": t, "摘要": "", "发布时间": f"2026-11-24 01:{m:02d}:00", "链接": ""}
          for m, t in enumerate(["英伟达股价涨幅收窄至30%"] + [f"黄仁勋{distinct(i)}" for i in range(12)], start=30)]
    sina = [{"时间": "2026-11-24 01:31:00", "内容": "英伟达涨幅收窄至30%。"}]

    def broken():
        raise ConnectionError("down")

    return {"em": lambda: em, "sina": lambda: sina, "ths": broken, "futu": lambda: [], "quotes": quotes}


def test_collect_attaches_the_actor_quote_and_records_feed_failures() -> None:
    asked = []

    def quotes(codes):
        asked.append(codes)
        return {"gb_nvda": ["英伟达", "165.3", "31.70", "2026-11-24 02:18:00"]}

    result = collect_headlines(NOW, _feeds(quotes))
    assert result["status"] == "ok"
    assert result["sources"]["ths"] == {"label": "同花顺", "status": "error", "error": "ConnectionError"}
    assert result["sources"]["em"]["count"] == 13
    assert asked == [["gb_nvda"]]
    (headline,) = result["headlines"]
    assert headline["sources"] == ["东方财富", "新浪"]
    assert headline["quotes"] == [{"code": "gb_nvda", "label": "英伟达", "value": 165.3,
                                   "change_pct": 0.317, "as_of": "2026-11-24 02:18"}]
    assert "quote_codes" not in headline


def test_headlines_stand_without_quotes_and_all_feeds_down_is_unavailable() -> None:
    def no_quotes(codes):
        raise TimeoutError

    result = collect_headlines(NOW, _feeds(no_quotes))
    assert result["headlines"][0]["quotes"] == []
    assert result["sources"]["quotes"]["status"] == "error"

    def broken():
        raise ConnectionError

    down = collect_headlines(NOW, {k: broken for k in ("em", "sina", "ths", "futu")})
    assert down["status"] == "unavailable" and down["headlines"] == []
