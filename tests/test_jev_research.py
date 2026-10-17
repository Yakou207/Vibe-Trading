from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import pytest

from fintech_quant.information.event_nlp import (
    analyze_items,
    financial_trend,
    research_consensus,
    tag_text,
)
from fintech_quant.information.stock_intel import collect_stock_intel, parse_financial_abstract
from fintech_quant.reports.picker import jev_payload, research_payload
from fintech_quant.research.jev import (
    QUESTIONS,
    LlmClient,
    apply_thresholds,
    ask_jev,
    client_from_env,
    parse_reply,
)
from test_picker_payload import _data


TODAY = date(2026, 10, 17)


def _fetchers(**overrides):
    base = {
        "news": lambda code: [
            {
                "新闻标题": "公司股东拟减持不超过1%股份",
                "新闻内容": "",
                "发布时间": "2026-10-15 18:00:00",
                "文章来源": "证券时报",
                "新闻链接": "https://x/1",
            }
        ],
        "notices": lambda code: [
            {
                "公告标题": "关于回购公司股份的进展公告",
                "公告类型": "回购",
                "公告日期": "2026-10-16",
                "网址": "https://x/2",
            },
            {
                "公告标题": "关于不存在违规担保及立案调查的说明",
                "公告类型": "其他",
                "公告日期": "2026-10-16",
                "网址": "https://x/3",
            },
        ],
        "research": lambda code: [
            {
                "报告名称": "业绩稳健",
                "东财评级": "买入",
                "机构": "A证券",
                "日期": "2026-09-30",
                "报告PDF链接": "",
                "2026-盈利预测-收益": 1.2,
            },
            {
                "报告名称": "维持评级",
                "东财评级": "增持",
                "机构": "B证券",
                "日期": "2026-08-30",
                "报告PDF链接": "",
                "2026-盈利预测-收益": 1.0,
            },
        ],
        "comment_score": lambda code: [{"交易日": "2026-10-16", "评分": 70.5}],
        "financials": lambda code: [
            {
                "报告期": "2026-06-30",
                "净利润同比增长率": "12.5%",
                "营业总收入同比增长率": "9.0%",
                "净资产收益率": "7.0%",
                "销售净利率": "20%",
                "净利润": "10.5亿",
            },
            {
                "报告期": "2026-03-31",
                "净利润同比增长率": "8.0%",
                "净资产收益率": "3.0%",
                "销售净利率": "19%",
            },
            {
                "报告期": "2025-12-31",
                "净利润同比增长率": "5.0%",
                "净资产收益率": False,
                "销售净利率": "18%",
            },
        ],
    }
    base.update(overrides)
    return base


def test_collect_reports_each_source_and_skips_qa_for_shanghai(tmp_path: Path) -> None:
    def broken(code):
        raise ConnectionError("upstream closed")

    def slow(code):
        time.sleep(1.0)
        return []

    intel = collect_stock_intel(
        "600001.SH",
        today=TODAY,
        cache_dir=tmp_path,
        fetchers=_fetchers(
            comment_score=broken, investor_qa=lambda code: [{"问题": "x"}], news=slow
        ),
        timeout=0.2,
    )

    assert intel["sources"]["comment_score"]["status"] == "failed"
    assert intel["sources"]["news"]["status"] == "timeout"
    assert intel["sources"]["notices"] == {"label": "公司公告", "status": "ok", "count": 2}
    assert "investor_qa" not in intel["sources"]
    assert intel["items"][0]["published_at"] == "2026-10-16"
    assert (tmp_path / "2026-10-17" / "600001.SH.json").exists()
    cached = collect_stock_intel("600001.SH", today=TODAY, cache_dir=tmp_path, fetchers={})
    assert cached["sources"] == intel["sources"]


def test_financial_abstract_parses_units_and_missing_values() -> None:
    rows = parse_financial_abstract(_fetchers()["financials"]("x"))

    assert rows[0]["period"] == "2026-06-30"
    assert rows[0]["net_profit"] == pytest.approx(10.5e8)
    assert rows[0]["net_profit_yoy"] == pytest.approx(0.125)
    assert rows[2]["roe"] is None


def test_event_tags_respect_negation() -> None:
    assert [t["tag"] for t in tag_text("股东拟减持股份")] == ["减持"]
    assert tag_text("关于不存在违规担保及立案调查的说明") == []
    assert [t["tag"] for t in tag_text("关于回购公司股份的进展公告")] == ["回购"]


def test_item_sentiment_weights_filings_over_investor_questions() -> None:
    items = [
        {"kind": "notice", "title": "董事会决议回购股份", "published_at": "2026-10-16"},
        {"kind": "qa", "title": "公司是否业绩不及预期？", "published_at": "2026-10-16"},
    ]

    result = analyze_items(items, today=TODAY)

    assert result["sentiment"] > 0
    assert result["event_counts"] == {"回购": 1, "业绩下滑": 1}


def test_consensus_and_financial_trend_annualise_interim_roe() -> None:
    intel_items = [
        {
            "kind": "research",
            "source": "A",
            "published_at": "2026-09-30",
            "rating": "买入",
            "eps_forecast": {"2026": 1.2},
        },
        {
            "kind": "research",
            "source": "B",
            "published_at": "2026-08-30",
            "rating": "减持",
            "eps_forecast": {"2026": 1.0},
        },
    ]
    consensus = research_consensus(intel_items, today=TODAY)
    assert consensus["bullish_share"] == 0.5 and consensus["bearish_share"] == 0.5
    assert consensus["eps_forecast_median"] == {"2026": 1.1}

    trend = financial_trend(parse_financial_abstract(_fetchers()["financials"]("x")))
    texts = [f["text"] for f in trend["flags"]]
    assert "ROE 14.0%（年化，报告期 7.0%）" in texts
    assert "净利润增速连续两期加速" in texts


def test_deepseek_key_selects_deepseek_flash_endpoint() -> None:
    client = client_from_env({"DEEPSEEK_API_KEY": "k"})
    assert client is not None
    assert (client.provider, client.model, client.base_url) == (
        "openai",
        "deepseek-flash",
        "https://api.deepseek.com",
    )


def test_env_file_loader_keeps_existing_environment(tmp_path, monkeypatch) -> None:
    from scripts.serve_trading_desk import load_env_file

    env = tmp_path / ".env"
    env.write_text(
        "# comment\nDEEPSEEK_API_KEY='abc'\nEMPTY=\nJEV_MODEL=from-file\n", encoding="utf-8"
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "placeholder")  # recorded, so teardown restores it
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    monkeypatch.setenv("JEV_MODEL", "from-shell")

    assert load_env_file(env) == ["DEEPSEEK_API_KEY"]
    import os

    assert os.environ["DEEPSEEK_API_KEY"] == "abc"
    assert os.environ["JEV_MODEL"] == "from-shell"


def test_api_key_in_model_slot_is_rejected_and_never_echoed() -> None:
    from fintech_quant.research.jev import config_status

    leaked = "sk-or-v1-" + "0" * 64
    status = config_status({"DEEPSEEK_API_KEY": "sk-real", "JEV_MODEL": leaked})

    assert status["configured"] is False
    assert leaked not in json.dumps(status, ensure_ascii=False)
    assert "API 密钥" in str(status["reason"])


def test_tls_context_verifies_certificates() -> None:
    import ssl

    from fintech_quant.research.jev import _ssl_context

    context = _ssl_context()
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True


def test_client_from_env_requires_key_and_explicit_openai_model() -> None:
    assert client_from_env({}) is None
    client = client_from_env({"ANTHROPIC_API_KEY": "k"})
    assert (
        client is not None
        and client.provider == "anthropic"
        and client.model == "claude-sonnet-5-5"
    )
    with pytest.raises(Exception, match="JEV_MODEL"):
        client_from_env({"OPENAI_API_KEY": "k"})
    assert (
        client_from_env(
            {
                "OPENAI_API_KEY": "k",
                "JEV_MODEL": "deepseek-chat",
                "JEV_BASE_URL": "https://api.deepseek.com/v1",
            }
        ).base_url
        == "https://api.deepseek.com/v1"
    )  # type: ignore[union-attr]


def _reply(scores: dict[str, float], stance: str = "support") -> str:
    answers = {
        q["id"]: {"score": scores.get(str(q["id"]), 0.5), "reason": "依据资料包"} for q in QUESTIONS
    }
    return "好的：\n" + json.dumps(
        {"answers": answers, "stance": stance, "summary": "测试", "key_risks": ["风险A"]},
        ensure_ascii=False,
    )


class FakeTransport:
    def __init__(self, reply: str, provider: str = "anthropic") -> None:
        self.reply, self.provider, self.calls = reply, provider, []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, dict(headers), json.loads(body)))
        if self.provider == "anthropic":
            return json.dumps({"content": [{"type": "text", "text": self.reply}]}).encode()
        return json.dumps({"choices": [{"message": {"content": self.reply}}]}).encode()


def test_anthropic_request_shape_and_deterministic_settings() -> None:
    transport = FakeTransport(_reply({}))
    client = LlmClient(provider="anthropic", api_key="secret", model="m", transport=transport)

    client.complete("sys", "user")

    url, headers, body = transport.calls[0]
    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == "secret" and headers["anthropic-version"] == "2023-06-01"
    assert body["temperature"] == 0 and body["system"] == "sys" and body["model"] == "m"


def test_parse_reply_requires_every_numeric_score() -> None:
    assert parse_reply(_reply({"crowding": 2.0}))["answers"]["crowding"]["score"] == 1.0
    with pytest.raises(ValueError, match="numeric score"):
        parse_reply('{"answers": {"crowding": {"score": "high"}}}')


def test_soft_thresholds_veto_and_never_upgrade_technical_avoid() -> None:
    veto = apply_thresholds(
        parse_reply(_reply({"negative_event_risk": 0.8})), technical_level="entry"
    )
    assert veto["judgment"] == "veto"
    assert veto["combined"] == "技术触发，但 Jev 否决：暂不入场"

    support = apply_thresholds(
        parse_reply(_reply({"earnings_support": 0.8, "setup_consistency": 0.7})),
        technical_level="avoid",
    )
    assert support["judgment"] == "support"
    assert support["combined"] == "技术面不支持入场，Jev 不能推翻"


def test_ask_jev_records_hashes_and_reuses_identical_packet(tmp_path: Path) -> None:
    transport = FakeTransport(_reply({}))
    client = LlmClient(provider="anthropic", api_key="k", model="m", transport=transport)
    packet = {"symbol": "600001.SH", "as_of": "2026-10-16", "technical_level": "entry"}

    first = ask_jev(packet, client=client, record_dir=tmp_path)
    second = ask_jev(packet, client=client, record_dir=tmp_path)

    assert len(transport.calls) == 1
    assert first["cached"] is False and second["cached"] is True
    assert first["advisory_only"] is True and len(first["packet_sha256"]) == 64
    assert list((tmp_path / "2026-10-16").glob("600001.SH-*.json"))


def test_research_and_jev_payload_end_to_end(tmp_path: Path) -> None:
    data = _data()
    research = research_payload(
        data,
        "600001",
        cache_dir=tmp_path / "cache",
        jev_record_dir=tmp_path / "jev",
        today=TODAY,
        fetchers=_fetchers(),
    )
    assert research["sources"]["research"]["count"] == 2
    assert research["nlp"]["event_counts"]["减持"] == 1
    assert "jev_record" not in research

    transport = FakeTransport(_reply({}, stance="neutral"), provider="openai")
    client = LlmClient(provider="openai", api_key="k", model="deepseek-chat", transport=transport)
    judgment = jev_payload(
        data,
        "600001",
        cache_dir=tmp_path / "cache",
        jev_record_dir=tmp_path / "jev",
        client=client,
        today=TODAY,
        fetchers=_fetchers(),
    )

    assert judgment["judgment"] == "neutral"
    sent = transport.calls[0][2]["messages"][1]["content"]
    assert "600001.SH" in sent and "公司股东拟减持" in sent
    again = research_payload(
        data, "600001", cache_dir=tmp_path / "cache", jev_record_dir=tmp_path / "jev", today=TODAY
    )
    assert again["jev_record"]["packet_sha256"] == judgment["packet_sha256"]
    assert again["jev_record"]["cached"] is True


def _decision_response(levels: dict[str, list[float]], stance: str = "neutral") -> bytes:
    answers = {
        qid: {
            "type": "score",
            "score": sum(i * p for i, p in enumerate(probs)),
            "probabilities": {str(i): p for i, p in enumerate(probs)},
            "confidence": max(probs),
        }
        for qid, probs in levels.items()
    }
    answers["stance"] = {
        "type": "choice",
        "choice": stance,
        "probabilities": {"support": 0.2, "neutral": 0.5, "avoid": 0.3},
        "confidence": 0.3,
    }
    return json.dumps(
        {
            "model": "typesafe/jev-1.14-20261014",
            "answers": answers,
            "usage": {"input_tokens": 455, "output_tokens": 70, "cost": 1.9e-05},
            "id": "gen-dec-1",
            "provider": "TypeSafe",
        }
    ).encode()


LEVELS = {
    "negative_event_risk": [0.05, 0.15, 0.6, 0.2],
    "earnings_support": [0.0, 0.1, 0.3, 0.5, 0.1],
    "catalyst_quality": [0.2, 0.5, 0.2, 0.1],
    "crowding": [0.3, 0.6, 0.1, 0.0],
    "setup_consistency": [0.0, 0.2, 0.6, 0.2],
}


def test_jev_model_names_normalise_to_openrouter_ids() -> None:
    from fintech_quant.research.jev import normalize_jev_model

    assert normalize_jev_model("Jev 1.14") == "typesafe/jev-1.14"
    assert normalize_jev_model("jev-1.13") == "typesafe/jev-1.13"
    assert normalize_jev_model("latest") == "~typesafe/jev-latest"
    assert normalize_jev_model("typesafe/jev-1.14") == "typesafe/jev-1.14"


def test_jev_model_selects_typesafe_decision_client_and_needs_openrouter_key() -> None:
    from fintech_quant.research.jev import JevDecisionClient, JevNotConfigured

    client = client_from_env(
        {"JEV_MODEL": "Jev 1.14", "OPENROUTER_API_KEY": "k", "DEEPSEEK_API_KEY": "d"}
    )
    assert isinstance(client, JevDecisionClient)
    assert (client.provider, client.model) == ("typesafe", "typesafe/jev-1.14")
    with pytest.raises(JevNotConfigured, match="OPENROUTER_API_KEY"):
        client_from_env({"JEV_MODEL": "Jev 1.14", "DEEPSEEK_API_KEY": "d"})


def test_decision_request_uses_typed_score_questions_and_stance_choice() -> None:
    from fintech_quant.research.jev import JevDecisionClient

    transport_calls: list = []

    def capture(url, headers, body, timeout):
        transport_calls.append((url, dict(headers), json.loads(body)))
        return _decision_response(LEVELS)

    client = JevDecisionClient(api_key="k", model="typesafe/jev-1.14", transport=capture)
    parsed, raw, meta = client.decide({"symbol": "600001.SH"})

    url, headers, body = transport_calls[0]
    assert url == "https://openrouter.ai/api/alpha/decisions"
    assert headers["authorization"] == "Bearer k"
    assert body["state"] == {"symbol": "600001.SH"}
    assert body["questions"]["negative_event_risk"]["type"] == "score"
    assert body["questions"]["negative_event_risk"]["criteria"] == ["无", "轻微", "明显", "严重"]
    assert body["questions"]["stance"]["type"] == "choice"
    assert parsed["answers"]["negative_event_risk"]["score"] == pytest.approx(
        (0.15 + 1.2 + 0.6) / 3, abs=1e-4
    )
    assert "明显" in parsed["answers"]["negative_event_risk"]["reason"]
    assert parsed["stance"] == "neutral"
    assert meta["served_model"] == "typesafe/jev-1.14-20261014"


def test_decision_probabilities_feed_the_same_soft_thresholds(tmp_path: Path) -> None:
    from fintech_quant.research.jev import JevDecisionClient

    client = JevDecisionClient(
        api_key="k", model="typesafe/jev-1.14", transport=lambda *a: _decision_response(LEVELS)
    )
    record = ask_jev(
        {"symbol": "600001.SH", "as_of": "2026-10-16", "technical_level": "entry"},
        client=client,
        record_dir=tmp_path,
    )

    risk = next(c for c in record["threshold_checks"] if c["id"] == "negative_event_risk")
    assert risk["score"] == pytest.approx(0.65, abs=1e-3) and risk["passed"] is False
    assert record["judgment"] == "veto"
    assert record["provider"] == "typesafe" and record["usage"]["cost"] == pytest.approx(1.9e-05)
    assert record["key_risks"] == ["负面事件风险偏高（明显）"]
    assert list((tmp_path / "2026-10-16").glob("600001.SH-*-typesafe_jev-1.14.json"))


def test_changing_question_wording_invalidates_saved_records(tmp_path: Path, monkeypatch) -> None:
    from fintech_quant.research import jev

    transport = FakeTransport(_reply({}))
    client = LlmClient(provider="anthropic", api_key="k", model="m", transport=transport)
    packet = {"symbol": "600001.SH", "as_of": "2026-10-16"}
    ask_jev(packet, client=client, record_dir=tmp_path)

    reworded = tuple({**q, "question": str(q["question"]) + "（改）"} for q in jev.QUESTIONS)
    monkeypatch.setattr(jev, "QUESTIONS", reworded)
    second = ask_jev(packet, client=client, record_dir=tmp_path)

    assert second["cached"] is False and len(transport.calls) == 2


def test_decision_without_probabilities_fails_closed() -> None:
    from fintech_quant.research.jev import JevDecisionClient

    client = JevDecisionClient(
        api_key="k", model="m", transport=lambda *a: json.dumps({"answers": {}}).encode()
    )
    with pytest.raises(ValueError, match="missing probabilities"):
        client.decide({})
