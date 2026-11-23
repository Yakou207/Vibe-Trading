"""Market headlines for the top of `/picks`: the few global flashes most likely to move today's
A-share open, chosen by fixed rules so every pick can be traced.

1. Pool: the last ``LOOKBACK_HOURS`` of 24/7 flashes from Eastmoney, Sina, Tonghuashun and Futu
   (财联社 is not used: its AkShare endpoint returns 404). Tonghuashun and Futu stamp their
   epoch times in the desk machine's local zone, so every time is converted to Shanghai.
2. The same flash relayed by several feeds is merged when the character bigrams of the shorter
   text mostly appear in the other (``SAME_STORY_OVERLAP``) and the times are close.
3. Each merged flash is scored: one point per extra feed carrying it, ``TOPIC_POINTS`` if it names
   a market-moving actor (``ENTITIES``) or carries a macro or global event tag, and up to
   ``HEAT_CAP`` points for how many other flashes in the pool share an actor or tag with it. Only
   flashes scoring at least ``MIN_SCORE`` become headlines, at most one per actor or tag.
4. A headline carries the live quote its actor maps to (Nvidia → NVDA, Fed → Nasdaq, ...) and the
   Shenwan sectors whose keywords it mentions (``global_intel.INDUSTRY_PROFILES``).

Display and research only: nothing reaches the counted strategy or the paper account.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fintech_quant.data.net_adaptive import run_parallel_with_deadline
from fintech_quant.information.event_nlp import MACRO_TAGS, tag_text
from fintech_quant.information.global_intel import INDUSTRY_PROFILES
from fintech_quant.information.premarket_live import sina_move, sina_quotes

SHANGHAI = ZoneInfo("Asia/Shanghai")
LOOKBACK_HOURS = 12
FETCH_DEADLINE_SECONDS = 15.0
SAME_STORY_OVERLAP = 0.6
SAME_STORY_HOURS = 3
TOPIC_POINTS = 2.0
HEAT_POINTS = 0.25
HEAT_CAP = 6.0
MIN_SCORE = 4.0
MAX_HEADLINES = 3
MAX_RELATED = 8
# Feed key → (label, whether its times are in the desk machine's local zone, not Shanghai).
FEEDS = {
    "em": ("东方财富", False),
    "sina": ("新浪", False),
    "ths": ("同花顺", True),
    "futu": ("富途", True),
}
# Actor → (aliases, Sina quote codes whose move shows the market's reaction).
ENTITIES: dict[str, tuple[tuple[str, ...], tuple[tuple[str, str], ...]]] = {
    "美联储": (("美联储", "鲍威尔", "FOMC"), (("gb_$ixic", "纳斯达克"),)),
    "中国央行": (("中国人民银行", "人民银行", "潘功胜", "降准", "LPR"), (("fx_susdcnh", "离岸人民币"),)),
    # Bare 财政部 also names the US or Brazilian ministry, so it is not an alias.
    "国内政策": (("国务院", "政治局", "证监会", "国常会", "发改委", "金融监管总局"), (("hf_CHA50CFD", "富时A50"),)),
    "特朗普": (("特朗普", "白宫", "万斯"), (("hf_CHA50CFD", "富时A50"),)),
    "英伟达": (("英伟达", "黄仁勋", "NVDA"), (("gb_nvda", "英伟达"),)),
    "苹果": (("苹果公司", "库克", "AAPL"), (("gb_aapl", "苹果"),)),
    "特斯拉": (("特斯拉", "马斯克", "TSLA"), (("gb_tsla", "特斯拉"),)),
    "台积电": (("台积电", "TSM"), (("gb_tsm", "台积电"),)),
    "原油": (("原油", "油价", "OPEC", "欧佩克"), (("hf_CL", "纽约原油"),)),
    "黄金": (("黄金", "金价"), (("hf_GC", "纽约黄金"),)),
}
MACRO_QUOTES = (("hf_CHA50CFD", "富时A50"),)
_SOURCE_SUFFIX = re.compile(r"[（(][^（）()]{1,8}[）)]\s*$")
_NOISE = re.compile(r"[\s，。、：；！？“”‘’《》【】（）()\[\],.:;!?\"'%·-]")

Fetcher = Callable[..., object]


def default_fetchers() -> dict[str, Fetcher]:
    def ak():
        return importlib.import_module("akshare")

    return {
        "em": lambda: ak().stock_info_global_em(),
        "sina": lambda: ak().stock_info_global_sina(),
        "ths": lambda: ak().stock_info_global_ths(),
        "futu": lambda: ak().stock_info_global_futu(),
        "quotes": sina_quotes,
    }


def collect_headlines(now: datetime, fetchers: Mapping[str, Fetcher] | None = None) -> dict[str, object]:
    fetch = fetchers or default_fetchers()
    tasks = {key: fetch[key] for key in FEEDS if key in fetch}
    values, errors = run_parallel_with_deadline(
        tasks, FETCH_DEADLINE_SECONDS, provider_prefix=None if fetchers else "headlines"
    )
    sources = {
        key: {"label": FEEDS[key][0], "status": "ok", "count": len(_records(values[key]))}
        if key in values else {"label": FEEDS[key][0], "status": "error", "error": type(errors[key]).__name__}
        for key in tasks
    }
    flashes = [f for key in values for f in parse_feed(key, _records(values[key]))]
    headlines = pick_headlines(flashes, now)
    codes = sorted({code for h in headlines for code, _ in h["quote_codes"]})  # type: ignore[union-attr]
    quotes: Mapping[str, Sequence[str]] = {}
    if codes and "quotes" in fetch:
        try:
            quotes = fetch["quotes"](codes)  # type: ignore[assignment]
        except Exception as exc:  # the headlines still stand without their quotes
            sources["quotes"] = {"label": "新浪行情", "status": "error", "error": type(exc).__name__}
    for headline in headlines:
        pairs = headline.pop("quote_codes")
        headline["quotes"] = [q for code, label in pairs if (q := sina_move(code, label, quotes.get(code)))]  # type: ignore[union-attr]
    ok = any(s["status"] == "ok" for s in sources.values())
    return {
        "status": "ok" if ok else "unavailable",
        "fetched_at": now.isoformat(timespec="seconds"),
        "lookback_hours": LOOKBACK_HOURS,
        "pool_size": len(flashes),
        "headlines": headlines,
        "sources": sources,
    }


def parse_feed(key: str, rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    label, local_zone = FEEDS[key]
    flashes = []
    for row in rows:
        stamp = str(row.get("发布时间") or row.get("时间") or "")[:19]
        title = str(row.get("标题") or "").strip()
        body = str(row.get("摘要") or row.get("内容") or "").strip()
        if not title:  # Sina and Futu flashes are often one block of text: 【title】body
            if body.startswith("【") and "】" in body:
                title, body = body[1 : body.index("】")], body[body.index("】") + 1 :]
            else:
                title = body
        try:
            naive = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        when = naive.astimezone(SHANGHAI) if local_zone else naive.replace(tzinfo=SHANGHAI)
        title = _SOURCE_SUFFIX.sub("", title).strip()
        if title:
            flashes.append({"source": label, "published_at": when, "title": title[:120],
                            "summary": body[:200], "url": str(row.get("链接") or "")})
    return flashes


def pick_headlines(flashes: Sequence[Mapping[str, object]], now: datetime) -> list[dict[str, object]]:
    since = now - timedelta(hours=LOOKBACK_HOURS)
    recent = sorted((f for f in flashes if since <= f["published_at"] <= now + timedelta(minutes=5)),  # type: ignore[operator]
                    key=lambda f: f["published_at"])  # type: ignore[arg-type,return-value]
    stories = merge_same_story(recent)
    for story in stories:
        text = f"{story['title']} {story['summary']}"
        story["entities"] = [name for name, (aliases, _) in ENTITIES.items() if any(a in text for a in aliases)]
        story["macro_tags"] = [str(t["tag"]) for t in tag_text(text) if t["tag"] in MACRO_TAGS]
        story["topics"] = story["entities"] + story["macro_tags"]  # type: ignore[operator]
    picked: list[dict[str, object]] = []
    used: set[str] = set()
    for story in sorted(stories, key=lambda s: (_score(s, stories), s["published_at"]), reverse=True):  # type: ignore[arg-type,return-value]
        score = _score(story, stories)
        topics: list[str] = story["topics"]  # type: ignore[assignment]
        if score < MIN_SCORE or len(picked) >= MAX_HEADLINES or not topics or used & set(topics):
            continue
        used.update(topics)
        picked.append(_headline(story, stories, score))
    return picked


def merge_same_story(flashes: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Greedy merge in time order; a story keeps its earliest time and the longest title."""
    stories: list[dict[str, object]] = []
    for flash in flashes:
        grams = _bigrams(str(flash["title"]))
        for story in stories:
            close = flash["published_at"] - story["last_at"] <= timedelta(hours=SAME_STORY_HOURS)  # type: ignore[operator]
            if close and _overlap(grams, story["grams"]) >= SAME_STORY_OVERLAP:  # type: ignore[arg-type]
                story["sources"].add(flash["source"])  # type: ignore[union-attr]
                story["last_at"] = flash["published_at"]
                if len(str(flash["title"])) > len(str(story["title"])):
                    story.update(title=flash["title"], summary=flash["summary"], grams=grams)
                if not story["url"]:
                    story["url"] = flash["url"]
                break
        else:
            stories.append({**flash, "sources": {flash["source"]}, "last_at": flash["published_at"], "grams": grams})
    return stories


def related_count(story: Mapping[str, object], stories: Sequence[Mapping[str, object]]) -> int:
    topics = set(story["topics"])  # type: ignore[arg-type]
    return sum(1 for other in stories if other is not story and topics & set(other["topics"]))  # type: ignore[arg-type]


def sectors_for(text: str) -> list[str]:
    return [industry for industry, profile in INDUSTRY_PROFILES.items() if any(k in text for k in profile["keywords"])]


def _score(story: Mapping[str, object], stories: Sequence[Mapping[str, object]]) -> float:
    score = len(story["sources"]) - 1.0  # type: ignore[arg-type]
    score += TOPIC_POINTS if story["topics"] else 0.0
    if story["topics"]:
        score += min(HEAT_CAP, HEAT_POINTS * related_count(story, stories))
    return score


def _headline(story: Mapping[str, object], stories: Sequence[Mapping[str, object]], score: float) -> dict[str, object]:
    topics = set(story["topics"])  # type: ignore[arg-type]
    related = [s for s in stories if s is not story and topics & set(s["topics"])]  # type: ignore[arg-type]
    related.sort(key=lambda s: s["published_at"], reverse=True)  # type: ignore[arg-type,return-value]
    pairs: list[tuple[str, str]] = []
    for name in story["entities"]:  # type: ignore[union-attr]
        pairs += [p for p in ENTITIES[str(name)][1] if p not in pairs]
    if story["macro_tags"] and not pairs:
        pairs += list(MACRO_QUOTES)
    text = f"{story['title']} {story['summary']}"
    return {
        "title": story["title"],
        "summary": story["summary"],
        "url": story["url"],
        "published_at": _iso(story["published_at"]),
        "sources": sorted(story["sources"]),  # type: ignore[arg-type]
        "entities": story["entities"],
        "macro_tags": story["macro_tags"],
        "related_count": len(related),
        "related": [{"title": s["title"], "published_at": _iso(s["published_at"]), "sources": sorted(s["sources"])}  # type: ignore[arg-type]
                    for s in related[:MAX_RELATED]],
        "sectors": sectors_for(text),
        "score": round(score, 2),
        "quote_codes": pairs,
    }


def _bigrams(text: str) -> set[str]:
    clean = _NOISE.sub("", text)
    return {clean[i : i + 2] for i in range(len(clean) - 1)} or {clean}


def _overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def _iso(when: object) -> str:
    return when.isoformat(timespec="seconds") if isinstance(when, datetime) else str(when)


def _records(frame: object) -> list[Mapping[str, object]]:
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        return list(frame.to_dict(orient="records"))  # type: ignore[union-attr]
    return list(frame)  # type: ignore[call-overload]
