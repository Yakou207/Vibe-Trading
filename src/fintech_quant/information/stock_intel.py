"""On-demand, multi-source information for one stock (display and Jev only).

Sources (AkShare): Eastmoney stock news, company announcements, broker research reports with
ratings and EPS forecasts, Shenzhen investor Q&A (互动易), Eastmoney composite comment scores and
the Tonghuashun financial abstract. Each source runs with its own timeout and reports its own
status, so one provider outage never hides the others. Results are cached once per stock per day.

None of this feeds the counted baseline strategy; its sentiment component is unchanged.
"""

from __future__ import annotations

import importlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping

Fetcher = Callable[[str], object]
SOURCE_LABELS = {
    "news": "东方财富个股新闻",
    "notices": "公司公告",
    "research": "券商研报",
    "investor_qa": "互动易问答（深市）",
    "comment_score": "千股千评综合评分",
    "financials": "同花顺财务摘要",
}
SOURCE_TIMEOUT_SECONDS = 20.0
NOTICE_LOOKBACK_DAYS = 120


def collect_stock_intel(
    symbol: str,
    *,
    today: date | None = None,
    cache_dir: Path | None = None,
    fetchers: Mapping[str, Fetcher] | None = None,
    timeout: float = SOURCE_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Collect every source for ``symbol`` (e.g. ``601398.SH``); cached per stock per day."""
    day = today or date.today()
    cache = cache_dir / day.isoformat() / f"{symbol}.json" if cache_dir else None
    if cache is not None and cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    active = dict(fetchers or default_fetchers(day))
    code = symbol.split(".")[0]
    if not code.startswith(("0", "3")):
        active.pop("investor_qa", None)

    sources: dict[str, dict[str, object]] = {}
    raw: dict[str, list[dict[str, object]]] = {}
    pool = ThreadPoolExecutor(max_workers=len(active) or 1)
    futures = {name: pool.submit(fetch, code) for name, fetch in active.items()}
    try:
        for name, future in futures.items():
            try:
                rows = _rows(future.result(timeout=timeout))
                raw[name] = rows
                sources[name] = {
                    "label": SOURCE_LABELS.get(name, name),
                    "status": "ok" if rows else "empty",
                    "count": len(rows),
                }
            except FutureTimeout:
                sources[name] = {
                    "label": SOURCE_LABELS.get(name, name),
                    "status": "timeout",
                    "count": 0,
                }
            except Exception as exc:  # each provider fails independently
                sources[name] = {
                    "label": SOURCE_LABELS.get(name, name),
                    "status": "failed",
                    "count": 0,
                    "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                }
    finally:
        pool.shutdown(wait=False, cancel_futures=True)  # a hung provider must not block the page

    items = (
        [_news_item(row) for row in raw.get("news", [])]
        + [_notice_item(row) for row in raw.get("notices", [])]
        + [_research_item(row) for row in raw.get("research", [])]
        + [_qa_item(row) for row in raw.get("investor_qa", [])]
    )
    items = sorted(
        (i for i in items if i["title"]), key=lambda i: str(i["published_at"]), reverse=True
    )
    payload = {
        "symbol": symbol,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "items": items,
        "comment_scores": [
            {"date": _text(row.get("交易日"))[:10], "score": _number(row.get("评分"))}
            for row in raw.get("comment_score", [])
        ],
        "financials": parse_financial_abstract(raw.get("financials", [])),
    }
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return payload


def default_fetchers(today: date) -> dict[str, Fetcher]:
    def ak():  # imported lazily so the module works without the data extra
        return importlib.import_module("akshare")

    begin = (today - timedelta(days=NOTICE_LOOKBACK_DAYS)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    return {
        "news": lambda code: ak().stock_news_em(symbol=code),
        "notices": lambda code: ak().stock_individual_notice_report(
            security=code, symbol="全部", begin_date=begin, end_date=end
        ),
        "research": lambda code: ak().stock_research_report_em(symbol=code),
        "investor_qa": lambda code: ak().stock_irm_cninfo(symbol=code),
        "comment_score": lambda code: ak().stock_comment_detail_zhpj_lspf_em(symbol=code),
        "financials": lambda code: ak().stock_financial_abstract_ths(
            symbol=code, indicator="按报告期"
        ),
    }


FINANCIAL_FIELDS = {
    "net_profit": "净利润",
    "net_profit_yoy": "净利润同比增长率",
    "deducted_profit_yoy": "扣非净利润同比增长率",
    "revenue": "营业总收入",
    "revenue_yoy": "营业总收入同比增长率",
    "eps": "基本每股收益",
    "net_margin": "销售净利率",
    "gross_margin": "销售毛利率",
    "roe": "净资产收益率",
    "debt_ratio": "资产负债率",
    "operating_cash_per_share": "每股经营现金流",
}


def parse_financial_abstract(
    rows: list[dict[str, object]], periods: int = 8
) -> list[dict[str, object]]:
    """Latest ``periods`` report periods, newest first, with 亿/万/% strings turned into numbers."""
    parsed = []
    for row in rows:
        period = _text(row.get("报告期"))[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", period):
            continue
        parsed.append(
            {
                "period": period,
                **{key: _number(row.get(col)) for key, col in FINANCIAL_FIELDS.items()},
            }
        )
    return sorted(parsed, key=lambda r: str(r["period"]), reverse=True)[:periods]


def _news_item(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "kind": "news",
        "source": _text(row.get("文章来源")) or "东方财富",
        "published_at": _text(row.get("发布时间"))[:19],
        "title": _text(row.get("新闻标题")),
        "summary": _text(row.get("新闻内容"))[:240],
        "url": _text(row.get("新闻链接")),
    }


def _notice_item(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "kind": "notice",
        "source": _text(row.get("公告类型")) or "公告",
        "published_at": _text(row.get("公告日期"))[:10],
        "title": _text(row.get("公告标题")),
        "summary": "",
        "url": _text(row.get("网址")),
    }


def _research_item(row: Mapping[str, object]) -> dict[str, object]:
    forecasts = {}
    for key, value in row.items():
        match = re.fullmatch(r"(\d{4})-盈利预测-收益", str(key))
        if match and _number(value) is not None:
            forecasts[match.group(1)] = _number(value)
    return {
        "kind": "research",
        "source": _text(row.get("机构")) or "研报",
        "published_at": _text(row.get("日期"))[:10],
        "title": _text(row.get("报告名称")),
        "summary": "",
        "url": _text(row.get("报告PDF链接")),
        "rating": _text(row.get("东财评级")),
        "eps_forecast": forecasts,
    }


def _qa_item(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "kind": "qa",
        "source": "互动易",
        "published_at": _text(row.get("提问时间"))[:19],
        "title": _text(row.get("问题"))[:200],
        "summary": "",
        "url": "",
    }


def _rows(result: object) -> list[dict[str, object]]:
    if result is None:
        return []
    if hasattr(result, "to_dict"):
        return list(result.to_dict(orient="records"))  # type: ignore[call-arg]
    return [dict(row) for row in result]  # type: ignore[union-attr]


def _text(value: object) -> str:
    if value is None or value is False or (isinstance(value, float) and value != value):
        return ""
    return str(value).strip()


def _number(value: object) -> float | None:
    text = _text(value).replace(",", "")
    if not text or text in {"False", "--", "-"}:
        return None
    scale = 1.0
    if text.endswith("%"):
        text, scale = text[:-1], 0.01
    elif text.endswith("万亿"):
        text, scale = text[:-2], 1e12
    elif text.endswith("亿"):
        text, scale = text[:-1], 1e8
    elif text.endswith("万"):
        text, scale = text[:-1], 1e4
    try:
        return float(text) * scale
    except ValueError:
        return None
