"""Deterministic A-share event NLP and financial-trend reading for the research panel.

Rules, not a model: every tag can be traced to the phrase that produced it, and the same text
always gives the same result. Negations such as 不存在/未发生/无 before a
negative phrase in the same clause (up to 12 characters back) cancel it. Item polarity is aggregated with a 14-day half-life.
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
    ("分红", 0.4, ("分红", "派息", "派发现金")),
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
    ("高管变动", -0.2, ("辞职", "离任")),
)
NEGATIONS = ("不存在", "未发生", "未出现", "无重大", "不涉及", "澄清", "否认")
HALF_LIFE_DAYS = 14.0
# Official filings carry full weight; investor questions are opinions, not company events.
KIND_WEIGHTS = {"notice": 1.0, "news": 0.7, "qa": 0.3}
BULLISH_RATINGS = {"买入", "增持", "强烈推荐", "推荐", "优于大市", "跑赢行业"}
BEARISH_RATINGS = {"减持", "卖出", "回避", "弱于大市"}


def tag_text(text: str) -> list[dict[str, object]]:
    tags = []
    for tag, weight, phrases in EVENT_RULES:
        hit = next((phrase for phrase in phrases if _unnegated(text, phrase, weight)), None)
        if hit is not None:
            tags.append({"tag": tag, "weight": weight, "phrase": hit})
    return tags


def _unnegated(text: str, phrase: str, weight: float) -> bool:
    for match in re.finditer(re.escape(phrase), text):
        window = re.split(r"[，。；;,!！?？\n]", text[max(0, match.start() - 12) : match.start()])[
            -1
        ]
        if weight >= 0 or not any(neg in window for neg in NEGATIONS):
            return True
    return False


def analyze_items(items: Sequence[Mapping[str, object]], *, today: date) -> dict[str, object]:
    scored = []
    weighted = total_weight = 0.0
    counts: Counter[str] = Counter()
    for item in items:
        if item.get("kind") == "research":
            continue  # ratings are summarised separately; titles are mostly promotional
        tags = tag_text(f"{item.get('title', '')} {item.get('summary', '')}")
        polarity = max(-1.0, min(1.0, sum(float(t["weight"]) for t in tags))) if tags else 0.0
        age = _age_days(str(item.get("published_at", "")), today)
        decay = (0.5 ** (age / HALF_LIFE_DAYS) if age is not None else 0.0) * KIND_WEIGHTS.get(
            str(item.get("kind")), 0.5
        )
        if tags:
            weighted += polarity * decay
            total_weight += decay
            counts.update(str(t["tag"]) for t in tags)
        scored.append(
            {**item, "tags": [t["tag"] for t in tags], "polarity": polarity, "age_days": age}
        )
    score = weighted / total_weight if total_weight else 0.0
    tagged = [s for s in scored if s["tags"]]
    return {
        "sentiment": round(score, 4),
        "label": "偏多" if score > 0.2 else "偏空" if score < -0.2 else "中性",
        "tagged_items": len(tagged),
        "total_items": len(scored),
        "event_counts": dict(counts.most_common()),
        "top_negative": sorted(
            (s for s in tagged if s["polarity"] < 0), key=lambda s: s["polarity"]
        )[:5],
        "top_positive": sorted(
            (s for s in tagged if s["polarity"] > 0), key=lambda s: -s["polarity"]
        )[:5],
        "items": scored,
    }


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
