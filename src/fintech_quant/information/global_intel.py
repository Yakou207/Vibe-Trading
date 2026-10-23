"""Global context for one A-share: worldwide news flashes and overnight overseas markets.

A-shares also move with things that are not about the company: a Nasdaq sell-off hits A-share
chip names, an oil spike moves refiners, a rate decision moves banks. Three inputs, fetched when
the picker analyses a stock and kept in memory for ``TTL_SECONDS`` (never written to disk):

- global 24/7 news flashes (Eastmoney, Sina, Tonghuashun);
- the last US session of the Nasdaq, S&P 500 and Dow;
- US peers mapped from the stock's Shenwan level-1 industry (e.g. 电子 → SOXX, NVDA, TSM).

A flash is kept only if it names the company (then it counts as the company's own news), mentions
one of the industry's keywords, or carries a macro or global event tag such as 降息 or 出口管制.
Overseas moves become at most two explicit items (the biggest index move, the peers' average) so
every signal traces to a number and one sell-off is not counted per ticker. Display and research only; nothing reaches the counted strategy.
"""

from __future__ import annotations

import importlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Callable, Mapping, Sequence

from fintech_quant.data.js_runtime import js_call
from fintech_quant.information.event_nlp import MACRO_TAGS, tag_text

Fetcher = Callable[..., object]
TTL_SECONDS = 600
SOURCE_TIMEOUT = 15.0
MAX_ITEMS = 40
INDEX_MOVE = 0.015  # |daily change| at which a US index becomes an item
PEER_MOVE = 0.03  # same for a single US peer or sector ETF
US_INDICES = ((".IXIC", "纳斯达克"), (".INX", "标普500"), (".DJI", "道琼斯"))

# Shenwan level-1 industry → keywords that make a global flash relevant, and US peers to watch.
INDUSTRY_PROFILES: dict[str, dict[str, tuple[str, ...]]] = {
    "电子": {
        "keywords": ("半导体", "芯片", "存储", "晶圆", "英伟达", "台积电", "苹果", "消费电子", "面板", "光刻"),
        "us": ("SOXX", "NVDA", "TSM"),
    },
    "计算机": {
        "keywords": ("人工智能", "AI", "大模型", "算力", "云计算", "数据中心", "软件", "信创", "英伟达"),
        "us": ("NVDA", "MSFT", "ORCL"),
    },
    "通信": {
        "keywords": ("光模块", "5G", "6G", "运营商", "算力", "卫星", "数据中心", "英伟达"),
        "us": ("NVDA", "AVGO"),
    },
    "传媒": {"keywords": ("游戏", "版号", "影视", "短剧", "AI应用", "广告"), "us": ()},
    "电力设备": {
        "keywords": ("光伏", "锂电", "储能", "风电", "新能源", "电网", "特斯拉", "电池"),
        "us": ("TSLA", "ENPH"),
    },
    "汽车": {
        "keywords": ("汽车", "新能源车", "电动车", "智能驾驶", "特斯拉", "车企", "汽车销量"),
        "us": ("TSLA",),
    },
    "有色金属": {
        "keywords": ("黄金", "金价", "铜", "铝", "锂", "稀土", "有色金属", "白银"),
        "us": ("NEM", "FCX"),
    },
    "石油石化": {
        "keywords": ("原油", "油价", "OPEC", "天然气", "炼化", "布伦特", "WTI"),
        "us": ("XOM", "CVX"),
    },
    "煤炭": {"keywords": ("煤炭", "煤价", "动力煤", "焦煤", "能源安全"), "us": ()},
    "基础化工": {"keywords": ("化工", "化工品", "原油", "化肥", "化纤"), "us": ()},
    "钢铁": {"keywords": ("钢铁", "钢价", "铁矿石", "粗钢"), "us": ()},
    "银行": {
        "keywords": ("银行", "LPR", "存款利率", "息差", "信贷", "降准", "社融"),
        "us": ("JPM",),
    },
    "非银金融": {
        "keywords": ("券商", "保险", "资本市场", "成交额", "印花税", "IPO", "两融"),
        "us": ("GS",),
    },
    "房地产": {"keywords": ("房地产", "楼市", "房价", "限购", "保交楼", "房贷"), "us": ()},
    "建筑装饰": {"keywords": ("基建", "专项债", "一带一路", "城中村"), "us": ()},
    "建筑材料": {"keywords": ("水泥", "玻璃", "基建", "房地产"), "us": ()},
    "医药生物": {
        "keywords": ("医药", "创新药", "集采", "医保", "FDA", "生物科技", "疫苗", "医疗器械"),
        "us": ("LLY", "PFE"),
    },
    "食品饮料": {"keywords": ("白酒", "消费", "食品", "饮料", "乳制品", "啤酒"), "us": ()},
    "家用电器": {"keywords": ("家电", "以旧换新", "空调", "冰箱", "出口"), "us": ()},
    "国防军工": {
        "keywords": ("军工", "国防", "军费", "航空发动机", "无人机", "导弹"),
        "us": ("LMT",),
    },
    "交通运输": {
        "keywords": ("航运", "运价", "集运", "航空", "物流", "港口", "油价"),
        "us": ("FDX",),
    },
    "公用事业": {"keywords": ("电价", "电力", "发电量", "用电量", "核电", "水电"), "us": ()},
    "机械设备": {
        "keywords": ("机器人", "人形机器人", "工程机械", "设备更新", "挖掘机"),
        "us": ("CAT",),
    },
    "农林牧渔": {"keywords": ("猪价", "生猪", "粮食", "种业", "饲料"), "us": ()},
    "商贸零售": {"keywords": ("消费", "零售", "免税", "电商"), "us": ()},
    "社会服务": {"keywords": ("旅游", "酒店", "出行", "消费"), "us": ()},
    "美容护理": {"keywords": ("化妆品", "医美", "消费"), "us": ()},
}

_CACHE: dict[tuple[str, str], tuple[float, object]] = {}
_CACHE_LOCK = threading.Lock()


def default_fetchers() -> dict[str, Fetcher]:
    def ak():
        return importlib.import_module("akshare")

    return {
        "news_em": lambda: ak().stock_info_global_em(),
        "news_sina": lambda: ak().stock_info_global_sina(),
        "news_ths": lambda: ak().stock_info_global_ths(),
        # Both decode with akshare's embedded V8 engine: one call at a time per process.
        "us_index": lambda symbol: js_call(ak().index_us_stock_sina, symbol=symbol),
        "us_stock": lambda symbol: js_call(ak().stock_us_daily, symbol=symbol),
    }


def collect_global_intel(
    *,
    name: str,
    symbol: str,
    industry: str | None,
    fetchers: Mapping[str, Fetcher] | None = None,
) -> dict[str, object]:
    active = {**default_fetchers(), **(fetchers or {})}
    profile = INDUSTRY_PROFILES.get(industry or "", {"keywords": (), "us": ()})
    jobs: dict[str, tuple[str, Callable[[], object]]] = {
        "news_em": ("东方财富全球快讯", lambda: _cached("news_em", "", active["news_em"])),
        "news_sina": ("新浪全球快讯", lambda: _cached("news_sina", "", active["news_sina"])),
        "news_ths": ("同花顺全球快讯", lambda: _cached("news_ths", "", active["news_ths"])),
    }
    for ticker, label in US_INDICES:
        jobs[ticker] = (label, lambda t=ticker: _cached("us_index", t, lambda: active["us_index"](t)))
    for ticker in profile["us"]:
        jobs[ticker] = (ticker, lambda t=ticker: _cached("us_stock", t, lambda: active["us_stock"](t)))
    results, sources = _run_all(jobs)

    news = []
    for key in ("news_em", "news_sina", "news_ths"):
        news.extend(_news_item(row, jobs[key][0]) for row in _rows(results.get(key)))
    items = select_relevant(news, name=name, symbol=symbol, keywords=profile["keywords"])
    overseas = []
    for ticker, label in (*US_INDICES, *((t, t) for t in profile["us"])):
        move = _last_move(_rows(results.get(ticker)))
        if move is not None:
            overseas.append({"ticker": ticker, "label": label, "index": ticker.startswith("."), **move})
    items.extend(move_items(overseas, industry))
    items.sort(key=lambda i: str(i.get("published_at", "")), reverse=True)
    return {
        "industry": industry,
        "industry_keywords": list(profile["keywords"]),
        "items": items[:MAX_ITEMS],
        "overseas": overseas,
        "sources": sources,
    }


def select_relevant(
    news: Sequence[Mapping[str, object]],
    *,
    name: str,
    symbol: str,
    keywords: Sequence[str],
) -> list[dict[str, object]]:
    """Keep a flash if it names the company, hits an industry keyword, or carries a macro tag."""
    code = symbol.split(".")[0]
    seen: set[str] = set()
    kept = []
    for item in news:
        text = f"{item.get('title', '')} {item.get('summary', '')}"
        key = str(item.get("title", ""))[:40]
        if not key or key in seen:
            continue
        seen.add(key)
        if (name and name in text) or code in text:
            kept.append({**item, "kind": "news", "relevance": "公司"})
            continue
        hits = [k for k in keywords if k in text]
        if hits:
            kept.append({**item, "kind": "global", "relevance": f"行业：{'、'.join(hits[:3])}"})
            continue
        macro = [t["tag"] for t in tag_text(text) if t["tag"] in MACRO_TAGS]
        if macro:
            kept.append({**item, "kind": "global", "relevance": f"宏观：{'、'.join(macro)}"})
    return kept


def move_items(overseas: Sequence[Mapping[str, object]], industry: str | None) -> list[dict[str, object]]:
    """At most two items, so one US sell-off is not counted once per ticker: the index with the
    largest move if it reaches INDEX_MOVE, and the industry peers' average if it reaches PEER_MOVE."""
    items = []
    indices = [o for o in overseas if o["index"]]
    if indices:
        top = max(indices, key=lambda o: abs(float(o["change"])))  # type: ignore[arg-type]
        if abs(float(top["change"])) >= INDEX_MOVE:  # type: ignore[arg-type]
            items.append(_move_item(f"{top['label']} {float(top['change']):+.1%}", top))  # type: ignore[arg-type]
    peers = [o for o in overseas if not o["index"]]
    if peers:
        mean = sum(float(o["change"]) for o in peers) / len(peers)  # type: ignore[arg-type]
        if abs(mean) >= PEER_MOVE:
            detail = "、".join(f"{o['label']} {float(o['change']):+.1%}" for o in peers)  # type: ignore[arg-type]
            items.append(
                _move_item(f"{industry}海外同业平均 {mean:+.1%}（{detail}）", {**peers[0], "change": mean})
            )
    return items


def _move_item(text: str, move: Mapping[str, object]) -> dict[str, object]:
    direction = "大涨" if float(move["change"]) > 0 else "大跌"  # type: ignore[arg-type]
    return {
        "kind": "global",
        "source": "美股行情",
        "published_at": f"{move['date']} 16:00:00",
        "title": f"美股隔夜 {text}",
        "summary": "",
        "url": "",
        "relevance": "海外市场",
        "move_tag": f"海外{direction}",
    }


def _last_move(rows: Sequence[Mapping[str, object]]) -> dict[str, object] | None:
    if len(rows) < 2:
        return None
    try:
        previous, last = float(rows[-2]["close"]), float(rows[-1]["close"])  # type: ignore[arg-type]
    except (KeyError, TypeError, ValueError):
        return None
    if previous <= 0:
        return None
    return {"date": str(rows[-1].get("date"))[:10], "close": last, "change": last / previous - 1}


def _news_item(row: Mapping[str, object], source: str) -> dict[str, object]:
    title = str(row.get("标题") or "")
    summary = str(row.get("摘要") or row.get("内容") or "")
    if not title:  # Sina flashes are one block of text: 【title】body
        text = summary
        if text.startswith("【") and "】" in text:
            title, summary = text[1 : text.index("】")], text[text.index("】") + 1 :]
        else:
            title, summary = text[:60], text
    return {
        "kind": "global",
        "source": source,
        "published_at": str(row.get("发布时间") or row.get("时间") or "")[:19],
        "title": title.strip(),
        "summary": summary.strip()[:200],
        "url": str(row.get("链接") or ""),
    }


def _run_all(
    jobs: Mapping[str, tuple[str, Callable[[], object]]],
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    results: dict[str, object] = {}
    sources: dict[str, dict[str, object]] = {}
    pool = ThreadPoolExecutor(max_workers=8)
    futures = {key: pool.submit(job) for key, (_, job) in jobs.items()}
    deadline = time.monotonic() + SOURCE_TIMEOUT
    for key, future in futures.items():
        label = jobs[key][0]
        try:
            results[key] = future.result(timeout=max(0.1, deadline - time.monotonic()))
            sources[key] = {"label": label, "status": "ok", "count": len(_rows(results[key]))}
        except FutureTimeout:
            sources[key] = {"label": label, "status": "timeout", "count": 0}
        except Exception as exc:  # one source failing must not hide the others
            sources[key] = {"label": label, "status": "error", "count": 0, "error": type(exc).__name__}
    pool.shutdown(wait=False, cancel_futures=True)
    return results, sources


def _cached(kind: str, key: str, fetch: Callable[[], object]) -> object:
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _CACHE.get((kind, key))
        if hit is not None and now - hit[0] < TTL_SECONDS:
            return hit[1]
    value = fetch()
    with _CACHE_LOCK:
        _CACHE[(kind, key)] = (now, value)
    return value


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _rows(result: object) -> list[dict[str, object]]:
    if result is None:
        return []
    if hasattr(result, "to_dict"):
        return list(result.to_dict(orient="records"))  # type: ignore[call-arg]
    return [dict(r) for r in result]  # type: ignore[union-attr]
