from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from fintech_quant.information import event_llm
from fintech_quant.information.event_nlp import analyze_items, tag_text

TODAY = date(2026, 10, 22)
NAME, SYMBOL = "华能国际", "600011.SH"


def _items() -> list[dict[str, object]]:
    return [
        {"kind": "news", "published_at": "2026-10-21 16:51:00",
         "title": "强势股追踪 主力资金连续5日净流入82股", "summary": "600011 ..."},
        {"kind": "news", "published_at": "2026-10-14 17:15:00",
         "title": "华能国际：Q3境内上网电量1133.21亿千瓦时 同比降9.9%", "summary": ""},
        {"kind": "notice", "published_at": "2026-10-15",
         "title": "华能国际:华能国际投资设立新能源公司的公告", "summary": ""},
        {"kind": "notice", "published_at": "2026-10-16",
         "title": "华能国际:华能国际关于第十二期中期票据发行的公告", "summary": ""},
        {"kind": "notice", "published_at": "2026-06-25",
         "title": "华能国际:华能国际2025年年度权益分派实施公告", "summary": ""},
    ]


class FakeClient:
    model = "deepseek-flash"

    def __init__(self, reply: dict[str, object]) -> None:
        self.reply, self.calls, self.prompts = reply, 0, []
        self.last_meta: dict[str, object] = {}

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        self.prompts.append(user)
        self.last_meta = {"served_model": "deepseek-flash", "usage": {"input_tokens": 300,
                                                                      "output_tokens": 40,
                                                                      "cost": None}}
        return json.dumps(self.reply, ensure_ascii=False)


def test_rules_cover_dividend_wording_and_reported_operating_figures() -> None:
    assert [t["tag"] for t in tag_text("2025年年度权益分派实施公告")] == ["分红"]
    assert [t["tag"] for t in tag_text("Q3上网电量 同比降9.9%")] == ["经营数据下降"]
    assert [t["tag"] for t in tag_text("销量同比增长12%")] == ["经营数据增长"]
    assert tag_text("同比下降幅度收窄") == []  # no figure, no tag
    assert [t["tag"] for t in tag_text("兴业银行关于副行长辞任的公告")] == ["高管变动"]


def test_round_up_news_is_listed_but_not_scored() -> None:
    nlp = analyze_items(_items(), today=TODAY, name=NAME, symbol=SYMBOL)

    roundup = [i for i in nlp["items"] if i.get("roundup")]
    assert [i["title"][:5] for i in roundup] == ["强势股追踪"]
    assert nlp["roundup_items"] == 1
    assert nlp["event_counts"] == {"经营数据下降": 1, "分红": 1}
    company_news = {"kind": "news", "published_at": "2026-10-20", "title": "公司股东拟减持股份"}
    assert analyze_items([company_news], today=TODAY, name=NAME, symbol=SYMBOL)["event_counts"] == {
        "减持": 1
    }


def test_parse_labels_keeps_only_known_ids_and_labels_and_clamps() -> None:
    reply = json.dumps({"items": [
        {"id": 0, "label": "中标/大单", "polarity": 3, "reason": "新项目"},
        {"id": 1, "label": "买入！", "polarity": 1},
        {"id": 9, "label": "回购", "polarity": 0.5},
        {"id": 2, "label": "无事件", "polarity": 0.7},
        {"id": 1, "label": "经营数据增长", "polarity": 0.2},  # needs a number: rules only
    ]}, ensure_ascii=False)

    labels = event_llm.parse_labels(reply, count=3)
    neutral = event_llm.parse_labels('{"items": [{"id": 0, "label": "高管变动", "polarity": 0}]}', 1)
    assert neutral[0]["label"] == "无事件"

    assert labels == {
        0: {"label": "中标/大单", "polarity": 1.0, "reason": "新项目"},
        2: {"label": "无事件", "polarity": 0.0, "reason": ""},
    }


def test_llm_labels_only_untagged_items_and_rules_stay_authoritative(tmp_path: Path) -> None:
    nlp = analyze_items(_items(), today=TODAY, name=NAME, symbol=SYMBOL)
    sent = event_llm.candidates(nlp["items"])
    assert [i["title"][-10:] for i in sent] == ["期中期票据发行的公告", "设立新能源公司的公告"]
    client = FakeClient({"items": [
        {"id": 0, "label": "无事件", "polarity": 0, "reason": "例行融资"},
        {"id": 1, "label": "中标/大单", "polarity": 0.4, "reason": "扩张新能源"},
    ]})

    result = event_llm.classify_events(
        nlp["items"], name=NAME, symbol=SYMBOL, client=client,  # type: ignore[arg-type]
        record_dir=tmp_path, today=TODAY,
    )

    assert "强势股追踪" not in client.prompts[0] and "权益分派" not in client.prompts[0]
    assert result["llm_tagged"] == 1 and result["sent_items"] == 2
    assert result["llm_items"][0]["label"] == "中标/大单"
    assert result["sentiment"] != nlp["sentiment"]
    assert result["usage"]["input_tokens"] == 300 and result["cached"] is False


def test_same_items_reuse_the_saved_labels_without_a_call(tmp_path: Path) -> None:
    nlp = analyze_items(_items(), today=TODAY, name=NAME, symbol=SYMBOL)
    client = FakeClient({"items": [{"id": 1, "label": "回购", "polarity": 0.8, "reason": "x"}]})
    first = event_llm.classify_events(
        nlp["items"], name=NAME, symbol=SYMBOL, client=client,  # type: ignore[arg-type]
        record_dir=tmp_path, today=TODAY,
    )

    again = event_llm.cached_result(
        nlp["items"], name=NAME, symbol=SYMBOL, model=client.model,
        record_dir=tmp_path, today=TODAY,
    )

    assert client.calls == 1
    assert again is not None and again["cached"] is True
    assert again["sentiment"] == first["sentiment"]


def test_client_requires_deepseek_key_and_ignores_jev_model() -> None:
    with pytest.raises(event_llm.EventLlmNotConfigured):
        event_llm.client_from_env({"OPENROUTER_API_KEY": "x", "JEV_MODEL": "Jev 1.14"})

    client = event_llm.client_from_env({"DEEPSEEK_API_KEY": "k", "JEV_MODEL": "Jev 1.14"})

    assert client.model == "deepseek-flash"


def test_deepseek_cost_uses_cache_split_and_time_of_day_tariff() -> None:
    from datetime import datetime, timezone

    from fintech_quant.research.jev import deepseek_cost

    usage = {"prompt_tokens": 1000, "prompt_cache_hit_tokens": 200, "completion_tokens": 500}
    peak = deepseek_cost("deepseek-flash", usage, datetime(2026, 10, 22, 2, 0, tzinfo=timezone.utc))
    off_peak = deepseek_cost(
        "deepseek-flash", usage, datetime(2026, 10, 24, 2, 0, tzinfo=timezone.utc)  # Saturday
    )

    assert peak == pytest.approx((200 * 0.006 + 800 * 0.3 + 500 * 1.2) / 1_000_000)
    assert off_peak == pytest.approx(peak / 2)
    assert deepseek_cost("claude-sonnet-5-5", usage, datetime.now(timezone.utc)) is None


def test_deepseek_client_records_an_estimated_cost() -> None:
    from fintech_quant.research.jev import LlmClient

    def transport(url, headers, body, timeout):  # noqa: ANN001
        return json.dumps({
            "model": "deepseek-flash",
            "usage": {"prompt_tokens": 1365, "completion_tokens": 331},
            "choices": [{"message": {"content": "{}"}}],
        }).encode("utf-8")

    client = LlmClient(provider="openai", api_key="k", model="deepseek-flash", transport=transport)
    client.complete("s", "u")

    assert client.last_meta["usage"]["cost"] > 0
    assert client.last_meta["usage"]["cost_estimated"] is True


def test_spend_prices_older_deepseek_records_from_tokens(tmp_path: Path) -> None:
    from fintech_quant.reports.picker import jev_spend

    record = {
        "model": "deepseek-flash",
        "created_at": "2026-10-22T18:00:00+08:00",
        "usage": {"input_tokens": 1365, "output_tokens": 331, "cost": None},
    }
    _path = tmp_path / "2026-10-22" / "x.json"
    _path.parent.mkdir(parents=True)
    _path.write_text(json.dumps(record), encoding="utf-8")

    spend = jev_spend(tmp_path, today=TODAY)

    assert spend["total_calls"] == 1 and spend["unpriced_calls"] == 0
    assert spend["total_cost"] == pytest.approx((1365 * 0.3 + 331 * 1.2) / 1_000_000 / 2)
