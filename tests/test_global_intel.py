from __future__ import annotations

from datetime import date

import pytest

from fintech_quant.information import global_intel
from fintech_quant.information.event_nlp import analyze_items, tag_text

TODAY = date(2026, 10, 23)


@pytest.fixture(autouse=True)
def _fresh_cache():
    global_intel.clear_cache()
    yield
    global_intel.clear_cache()


def _bars(closes: list[float], start: int = 20) -> list[dict[str, object]]:
    return [{"date": f"2026-10-{start + i:02d}", "close": c} for i, c in enumerate(closes)]


def _fetchers(**overrides):
    base = {
        "news_em": lambda: [
            {"标题": "美国宣布扩大对华芯片出口管制", "摘要": "涉及先进制程", "发布时间": "2026-10-23 08:00:00", "链接": "u1"},
            {"标题": "北方华创获大额订单", "摘要": "", "发布时间": "2026-10-23 09:00:00", "链接": "u2"},
            {"标题": "某地举办美食节", "摘要": "游客众多", "发布时间": "2026-10-23 10:00:00", "链接": "u3"},
            {"标题": "存储芯片现货价格本周上涨", "摘要": "", "发布时间": "2026-10-22 21:00:00", "链接": "u4"},
        ],
        "news_sina": lambda: [{"时间": "2026-10-23 07:00:00", "内容": "【美联储宣布降息25个基点】符合预期"}],
        "news_ths": lambda: [],
        "us_index": lambda symbol: _bars([100.0, 97.5]) if symbol == ".IXIC" else _bars([100.0, 100.5]),
        "us_stock": lambda symbol: _bars([100.0, 95.0]) if symbol == "NVDA" else _bars([100.0, 97.0]),
    }
    base.update(overrides)
    return base


def test_keeps_company_industry_and_macro_flashes_and_drops_the_rest() -> None:
    world = global_intel.collect_global_intel(
        name="北方华创", symbol="002371.SZ", industry="电子", fetchers=_fetchers()
    )

    by_title = {i["title"]: i for i in world["items"]}
    assert by_title["北方华创获大额订单"]["kind"] == "news"  # names the company: its own news
    assert by_title["北方华创获大额订单"]["relevance"] == "公司"
    assert by_title["存储芯片现货价格本周上涨"]["relevance"].startswith("行业：")
    assert by_title["美联储宣布降息25个基点"]["relevance"] == "宏观：降息/宽松"
    assert "某地举办美食节" not in by_title
    assert world["sources"]["news_em"]["status"] == "ok"


def test_large_overseas_moves_become_traceable_items() -> None:
    world = global_intel.collect_global_intel(
        name="北方华创", symbol="002371.SZ", industry="电子", fetchers=_fetchers()
    )

    moves = [i for i in world["items"] if i.get("move_tag")]
    titles = sorted(i["title"] for i in moves)
    assert titles == [  # one item per group, not one per ticker
        "美股隔夜 电子海外同业平均 -3.7%（SOXX -3.0%、NVDA -5.0%、TSM -3.0%）",
        "美股隔夜 纳斯达克 -2.5%",
    ]
    assert {o["ticker"] for o in world["overseas"]} == {".IXIC", ".INX", ".DJI", "SOXX", "NVDA", "TSM"}

    nlp = analyze_items(world["items"], today=TODAY, name="北方华创", symbol="002371.SZ")
    assert nlp["event_counts"]["海外大跌"] == 2
    assert nlp["event_counts"]["制裁/出口管制"] == 1


def test_a_failing_source_is_reported_without_hiding_the_others() -> None:
    def broken():
        raise ConnectionError("down")

    world = global_intel.collect_global_intel(
        name="工商银行", symbol="601398.SH", industry="银行", fetchers=_fetchers(news_em=broken)
    )

    assert world["sources"]["news_em"]["status"] == "error"
    assert any(i["title"] == "美联储宣布降息25个基点" for i in world["items"])
    assert {o["ticker"] for o in world["overseas"]} == {".IXIC", ".INX", ".DJI", "JPM"}


def test_feeds_are_reused_within_the_ttl() -> None:
    calls = {"n": 0}

    def counted():
        calls["n"] += 1
        return []

    for _ in range(2):
        global_intel.collect_global_intel(
            name="x", symbol="600000.SH", industry=None, fetchers=_fetchers(news_em=counted)
        )

    assert calls["n"] == 1


def test_global_flashes_only_carry_macro_and_industry_level_tags() -> None:
    items = [
        {"kind": "global", "published_at": "2026-10-23", "title": "武汉天源：联合体中标36.4亿元储能项目"},
        {"kind": "global", "published_at": "2026-10-23", "title": "存储芯片现货价格本周上涨，厂商提价"},
        {"kind": "global", "published_at": "2026-10-23", "title": "白宫称俄乌同意暂时停火，此前曾发生空袭"},
    ]

    nlp = analyze_items(items, today=TODAY, name="华能国际", symbol="600011.SH")

    assert nlp["event_counts"] == {"涨价": 1, "地缘缓和": 1}


def test_stock_count_headlines_are_round_ups() -> None:
    item = {"kind": "news", "published_at": "2026-10-23", "title": "科创板平均股价43.87元，83股股价超百元"}

    nlp = analyze_items([item], today=TODAY, name="中芯国际", symbol="688981.SH")

    assert nlp["roundup_items"] == 1 and nlp["event_counts"] == {}


def test_lexicon_covers_global_and_company_operations() -> None:
    assert [t["tag"] for t in tag_text("美国宣布对华芯片出口管制升级")] == ["制裁/出口管制"]
    assert [t["tag"] for t in tag_text("公司产品获得FDA批准")] == ["获批/认证"]
    assert [t["tag"] for t in tag_text("关于撤销风险警示的公告")] == ["摘帽"]
    assert [t["tag"] for t in tag_text("纳指跌超3%")] == ["海外大跌"]


def test_research_panel_merges_global_items_and_overseas_context(tmp_path) -> None:
    from fintech_quant.reports.live_stock import LiveContext
    from fintech_quant.reports.picker import research_payload
    from test_jev_research import _fetchers as intel_fetchers
    from test_live_stock import _fetchers as live_fetchers
    from test_picker_payload import _data

    industry_rows = [{"变更日期": "2021-07-30", "分类标准编码": "008003", "行业门类": "电子"}]
    live = LiveContext(
        cache_dir=tmp_path / "live",
        fetchers=live_fetchers(industry=lambda **kw: industry_rows),
        today=TODAY,
    )

    research = research_payload(
        _data(),
        "600001",
        cache_dir=tmp_path / "cache",
        jev_record_dir=None,
        today=TODAY,
        fetchers=intel_fetchers(),
        live=live,
        global_fetchers=_fetchers(),
    )

    assert research["global"]["industry"] == "电子"
    assert {o["ticker"] for o in research["global"]["overseas"]} >= {".IXIC", "SOXX"}
    assert research["sources"]["news_em"]["label"] == "东方财富全球快讯"
    assert any(i.get("kind") == "global" for i in research["items"])
    assert research["nlp"]["event_counts"]["海外大跌"] == 2


def test_javascript_decoded_calls_never_overlap() -> None:
    import threading
    import time as clock

    from fintech_quant.data.js_runtime import js_call

    active, peak, lock = [0], [0], threading.Lock()

    def call() -> None:
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        clock.sleep(0.02)
        with lock:
            active[0] -= 1

    threads = [threading.Thread(target=js_call, args=(call,)) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert peak[0] == 1
