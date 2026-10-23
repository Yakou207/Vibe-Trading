"""Deterministic A-share event NLP and financial-trend reading for the research panel.

Rules, not a model: every tag can be traced to the phrase that produced it, and the same text
always gives the same result. Negations such as 不存在/未发生/无 before a
negative phrase in the same clause (up to 12 characters back) cancel it. Item polarity is aggregated with a 14-day half-life.
Market round-ups that merely list the stock (强势股追踪, 资金流向日报, …; the title does not name
it) are shown but not scored. Items the rules leave untagged can be labelled by an LLM
(``information/event_llm.py``); those labels are kept separate and marked as such.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime
from statistics import median
from typing import Mapping, Sequence


# (tag, polarity weight, phrases)
EVENT_RULES: tuple[tuple[str, float, tuple[str, ...]], ...] = (
    ("增持", 0.8, ("增持",)),
    ("回购", 0.8, ("回购",)),
    ("业绩预增", 1.0, ("预增", "扭亏", "预盈", "业绩大增", "超预期")),
    ("中标/大单", 0.6, ("中标", "签订重大合同", "订单")),
    ("分红", 0.4, ("分红", "派息", "派发现金", "权益分派", "利润分配")),
    ("评级上调", 0.6, ("上调评级", "首次覆盖", "买入评级", "增持评级")),
    ("减持", -0.9, ("减持",)),
    ("质押/冻结", -0.7, ("质押", "冻结", "司法拍卖")),
    ("解禁", -0.4, ("解禁",)),
    ("监管问询", -0.6, ("问询函", "监管函", "关注函", "警示函")),
    ("立案/处罚", -1.0, ("立案", "行政处罚", "处罚决定", "被调查")),
    ("诉讼/仲裁", -0.6, ("诉讼", "仲裁")),
    ("业绩下滑", -1.0, ("预减", "预亏", "首亏", "亏损", "下修", "业绩下滑", "不及预期")),
    ("增发稀释", -0.3, ("定增", "向特定对象发行", "非公开发行")),
    ("退市/ST", -1.0, ("退市", "*ST", "风险警示")),
    ("高管变动", -0.2, ("辞职", "辞任", "离任")),
    # Company operations
    ("股权激励", 0.4, ("股权激励", "员工持股计划")),
    ("战略合作", 0.3, ("战略合作", "战略投资", "签署合作协议")),
    ("获批/认证", 0.5, ("获批", "获得批准", "获得注册", "通过认证", "FDA批准", "获准上市")),
    ("涨价", 0.4, ("涨价", "提价", "上调价格", "价格上调", "价格上涨", "价格显著上涨", "价格大涨")),
    ("降价", -0.3, ("降价", "下调价格", "价格下调", "价格战", "价格下跌", "价格大跌")),
    ("投产/扩产", 0.3, ("投产", "扩产", "产能释放", "量产")),
    ("停产/事故", -0.7, ("停产", "停工", "安全事故", "爆炸", "火灾", "泄漏")),
    ("召回", -0.5, ("召回",)),
    ("违约/逾期", -0.9, ("违约", "逾期", "无法兑付", "债务危机", "破产重整")),
    ("摘帽", 0.6, ("撤销风险警示", "摘帽")),
    # Macro, policy and global events (also used to pick relevant global news flashes)
    ("降息/宽松", 0.5, ("降息", "降准", "宽松", "放水", "量化宽松")),
    ("加息/收紧", -0.5, ("加息", "缩表", "紧缩")),
    ("政策支持", 0.4, ("政策支持", "补贴", "刺激政策", "稳增长", "专项债")),
    ("关税/贸易摩擦", -0.6, ("加征关税", "关税上调", "贸易战", "贸易摩擦", "反倾销", "反补贴")),
    ("关税缓和", 0.5, ("关税豁免", "下调关税", "取消关税", "暂停加征", "贸易协议")),
    ("制裁/出口管制", -0.8, ("制裁", "出口管制", "实体清单", "禁令", "断供")),
    ("地缘冲突", -0.5, ("冲突升级", "开战", "空袭", "导弹袭击", "军事行动")),
    ("地缘缓和", 0.3, ("停火", "停战", "和谈", "缓和局势", "达成和平")),
    ("海外大涨", 0.5, ("美股大涨", "美股集体收涨", "纳指大涨", "纳指涨超", "费城半导体指数涨超")),
    ("海外大跌", -0.5, ("美股大跌", "美股集体收跌", "纳指大跌", "纳指跌超", "费城半导体指数跌超", "暴跌", "闪崩")),
)
# Economy-wide events: they make a global flash relevant to any stock.
MACRO_TAGS = frozenset(
    {
        "降息/宽松", "加息/收紧", "关税/贸易摩擦", "关税缓和",
        "制裁/出口管制", "地缘冲突", "地缘缓和", "海外大涨", "海外大跌",
    }
)
# A global flash is about other companies or the economy, so company events in it (another
# firm's order, buyback, probe) are not this stock's events; only these tags count for it.
GLOBAL_TAGS = MACRO_TAGS | {"涨价", "降价", "政策支持"}
# Synthetic overseas-market items (global_intel) carry their tag directly.
MOVE_WEIGHTS = {"海外大涨": 0.5, "海外大跌": -0.5}
# Reported operating figures with a number: 上网电量同比降9.9%, 销量同比增长12%.
PATTERN_RULES: tuple[tuple[str, float, re.Pattern[str]], ...] = (
    ("经营数据增长", 0.4, re.compile(r"同比(?:增长|上升|提升|增加|增)\s*\d")),
    ("经营数据下降", -0.4, re.compile(r"同比(?:下降|下滑|减少|降)\s*\d")),
)
ROUNDUP_COUNT = re.compile(r"\d+(?:只|家)?(?:个)?股")  # 主力资金连续5日净流入82股, 83股股价超百元
ROUNDUP_HINTS = ("强势股", "资金流向", "突破年线", "龙虎榜", "涨停", "跌停", "个股", "盘点", "一览", "日报", "排行", "榜单", "名单", "概念股", "平均股价")
NEGATIONS = ("不存在", "未发生", "未出现", "无重大", "不涉及", "澄清", "否认", "撤销", "解除")
HALF_LIFE_DAYS = 14.0
# Official filings carry full weight; investor questions are opinions, not company events;
# global flashes and overseas moves affect the stock only indirectly.
KIND_WEIGHTS = {"notice": 1.0, "news": 0.7, "qa": 0.3, "global": 0.4}
BULLISH_RATINGS = {"买入", "增持", "强烈推荐", "推荐", "优于大市", "跑赢行业"}
BEARISH_RATINGS = {"减持", "卖出", "回避", "弱于大市"}


def tag_text(text: str) -> list[dict[str, object]]:
    tags = []
    for tag, weight, phrases in EVENT_RULES:
        hit = next((phrase for phrase in phrases if _unnegated(text, phrase, weight)), None)
        if hit is not None:
            tags.append({"tag": tag, "weight": weight, "phrase": hit})
    for tag, weight, pattern in PATTERN_RULES:
        match = pattern.search(text)
        if match is not None:
            tags.append({"tag": tag, "weight": weight, "phrase": match.group(0)})
    if any(t["tag"] == "地缘缓和" for t in tags):  # 同意停火 after 空袭 reports is de-escalation
        tags = [t for t in tags if t["tag"] != "地缘冲突"]
    return tags


def is_roundup(item: Mapping[str, object], *, name: str = "", symbol: str = "") -> bool:
    """Market round-up news that merely lists the stock: round-up wording, and the title names
    neither the stock nor its code (company news often says 公司 instead of the name)."""
    if item.get("kind") != "news" or not (name or symbol):
        return False
    title = str(item.get("title", ""))
    code = symbol.split(".")[0]
    if (name and name in title) or (code and code in title):
        return False
    return any(hint in title for hint in ROUNDUP_HINTS) or bool(ROUNDUP_COUNT.search(title))


def _unnegated(text: str, phrase: str, weight: float) -> bool:
    for match in re.finditer(re.escape(phrase), text):
        window = re.split(r"[，。；;,!！?？\n]", text[max(0, match.start() - 12) : match.start()])[
            -1
        ]
        if weight >= 0 or not any(neg in window for neg in NEGATIONS):
            return True
    return False


def analyze_items(
    items: Sequence[Mapping[str, object]], *, today: date, name: str = "", symbol: str = ""
) -> dict[str, object]:
    scored = []
    counts: Counter[str] = Counter()
    for item in items:
        if item.get("kind") == "research":
            continue  # ratings are summarised separately; titles are mostly promotional
        age = _age_days(str(item.get("published_at", "")), today)
        if is_roundup(item, name=name, symbol=symbol):
            scored.append({**item, "tags": [], "polarity": 0.0, "age_days": age, "roundup": True})
            continue
        tags = tag_text(f"{item.get('title', '')} {item.get('summary', '')}")
        if item.get("kind") == "global":
            tags = [t for t in tags if t["tag"] in GLOBAL_TAGS]
        if item.get("move_tag") in MOVE_WEIGHTS:
            tag = str(item["move_tag"])
            tags = [{"tag": tag, "weight": MOVE_WEIGHTS[tag], "phrase": tag}]
        polarity = max(-1.0, min(1.0, sum(float(t["weight"]) for t in tags))) if tags else 0.0
        counts.update(str(t["tag"]) for t in tags)
        scored.append(
            {**item, "tags": [t["tag"] for t in tags], "polarity": polarity, "age_days": age}
        )
    score = decayed_sentiment(scored)
    tagged = [s for s in scored if s["tags"]]
    return {
        "sentiment": round(score, 4),
        "label": sentiment_label(score),
        "tagged_items": len(tagged),
        "total_items": len(scored),
        "roundup_items": sum(1 for s in scored if s.get("roundup")),
        "event_counts": dict(counts.most_common()),
        "top_negative": sorted(
            (s for s in tagged if s["polarity"] < 0), key=lambda s: s["polarity"]
        )[:5],
        "top_positive": sorted(
            (s for s in tagged if s["polarity"] > 0), key=lambda s: -s["polarity"]
        )[:5],
        "items": scored,
    }


def decayed_sentiment(scored: Sequence[Mapping[str, object]]) -> float:
    """Tagged items' polarity, weighted by source kind and a 14-day half-life."""
    weighted = total_weight = 0.0
    for item in scored:
        if not item.get("tags"):
            continue
        age = item.get("age_days")
        decay = (
            0.5 ** (float(age) / HALF_LIFE_DAYS) if isinstance(age, (int, float)) else 0.0  # type: ignore[arg-type]
        ) * KIND_WEIGHTS.get(str(item.get("kind")), 0.5)
        weighted += float(item["polarity"]) * decay  # type: ignore[arg-type]
        total_weight += decay
    return weighted / total_weight if total_weight else 0.0


def sentiment_label(score: float) -> str:
    return "偏多" if score > 0.2 else "偏空" if score < -0.2 else "中性"


def research_consensus(
    items: Sequence[Mapping[str, object]], *, today: date, days: int = 90
) -> dict[str, object]:
    recent = [
        i
        for i in items
        if i.get("kind") == "research"
        and (_age_days(str(i.get("published_at", "")), today) or 9999) <= days
    ]
    ratings = Counter(str(i.get("rating") or "未评级") for i in recent)
    bullish = sum(n for r, n in ratings.items() if r in BULLISH_RATINGS)
    bearish = sum(n for r, n in ratings.items() if r in BEARISH_RATINGS)
    forecasts: dict[str, list[float]] = {}
    for item in recent:
        for year, eps in dict(item.get("eps_forecast") or {}).items():  # type: ignore[arg-type]
            forecasts.setdefault(str(year), []).append(float(eps))
    return {
        "window_days": days,
        "reports": len(recent),
        "institutions": len({i.get("source") for i in recent}),
        "ratings": dict(ratings.most_common()),
        "bullish_share": bullish / len(recent) if recent else None,
        "bearish_share": bearish / len(recent) if recent else None,
        "eps_forecast_median": {y: round(median(v), 4) for y, v in sorted(forecasts.items())},
    }


def financial_trend(periods: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Read the latest report periods (newest first) into plain-language flags."""
    if not periods:
        return {"flags": [], "score": None}
    latest = periods[0]
    flags: list[dict[str, object]] = []

    def flag(text: str, polarity: int) -> None:
        flags.append({"text": text, "polarity": polarity})

    for key, label in (
        ("revenue_yoy", "营收同比"),
        ("net_profit_yoy", "净利润同比"),
        ("deducted_profit_yoy", "扣非净利润同比"),
    ):
        value = latest.get(key)
        if isinstance(value, float):
            flag(f"{label} {value:+.1%}", 1 if value > 0.05 else -1 if value < 0 else 0)
    profit = [
        p.get("net_profit_yoy") for p in periods[:5] if isinstance(p.get("net_profit_yoy"), float)
    ]
    if len(profit) >= 3:
        if profit[0] > profit[1] > profit[2]:
            flag("净利润增速连续两期加速", 1)
        elif profit[0] < profit[1] < profit[2]:
            flag("净利润增速连续两期放缓", -1)
    roe = latest.get("roe")
    if isinstance(roe, float):
        months = int(str(latest.get("period", "0000-12"))[5:7] or 12)
        annual = roe * 12 / months
        suffix = "" if months == 12 else f"（年化，报告期 {roe:.1%}）"
        flag(f"ROE {annual:.1%}{suffix}", 1 if annual >= 0.12 else -1 if annual < 0.06 else 0)
    margins = [p.get("net_margin") for p in periods[:5] if isinstance(p.get("net_margin"), float)]
    if (
        len(margins) >= 2
        and periods[0].get("period", "")[5:]
        == periods[min(4, len(periods) - 1)].get("period", "")[5:]
    ):
        delta = margins[0] - margins[-1]
        flag(
            f"销售净利率同比 {delta * 100:+.1f} 个百分点",
            1 if delta > 0.005 else -1 if delta < -0.005 else 0,
        )
    debt = latest.get("debt_ratio")
    if isinstance(debt, float) and debt > 0.8:
        flag(f"资产负债率 {debt:.0%}（金融业通常较高）", 0)
    cash = latest.get("operating_cash_per_share")
    if isinstance(cash, float) and cash < 0:
        flag("每股经营现金流为负", -1)
    signs = [f["polarity"] for f in flags if f["polarity"] != 0]
    return {
        "latest_period": latest.get("period"),
        "flags": flags,
        "score": round(sum(signs) / len(signs), 3) if signs else 0.0,
    }


def _age_days(published: str, today: date) -> float | None:
    text = published.strip()
    for fmt, size in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            moment = datetime.strptime(text[:size], fmt)
            return max(
                0.0, (datetime.combine(today, datetime.min.time()) - moment).total_seconds() / 86400
            )
        except ValueError:
            continue
    return None
