"""Read-only data layer for the desk's stock-picker page.

Everything comes from artifacts the canonical pipeline state already hash-binds: the processed
signal-price (hfq) and execution-price (unadjusted) snapshots, the decision report, the current
constituent list and the membership history. Chart levels are shown on the current unadjusted
price scale (hfq level x latest unadjusted/hfq close ratio), like a forward-adjusted chart.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Mapping

from fintech_quant.data.historical_universe import active_symbols, load_membership_intervals
from fintech_quant.data.manifest_chain import load_verified_manifest
from fintech_quant.execution.paper_evidence import approved_paper_policy, verify_file_reference
from fintech_quant.information import event_llm
from fintech_quant.information.event_nlp import analyze_items, financial_trend, research_consensus
from fintech_quant.information.global_intel import collect_global_intel
from fintech_quant.information.stock_intel import collect_stock_intel
from fintech_quant.reports.live_stock import (
    LiveContext,
    analyze_live,
    resolve_any,
    stock_industry,
)
from fintech_quant.research.jev import (
    JevDecisionClient,
    LlmClient,
    ask_jev,
    client_from_env,
    config_status,
    deepseek_cost,
    questions_sha,
    record_name,
)
from fintech_quant.research.momentum_pool import pool_metrics
from fintech_quant.research.momentum_pool_v2 import pool_metrics as pool_v2_metrics
from fintech_quant.research.momentum_pool_v2 import position_status
from fintech_quant.research.momentum_setup import (
    Bar,
    SymbolSeries,
    analyze_at,
    momentum_table,
    screen,
)
from fintech_quant.research.scoring_v2 import snapshot_view


CHART_SESSIONS = 160
VERDICTS = {
    "trigger": ("entry", "入场候选：今日急跌触及共振支撑并收复"),
    "setup": ("watch", "观察：强势平台成立，等待回踩共振区后收复"),
    "leader_weak_base": ("wait", "强势但平台内强度不足，暂不入场"),
    "leader_no_base": ("wait", "强势但尚未形成 8 周整理平台，不追高"),
    "avoid": ("avoid", "回避"),
    "no_bar": ("avoid", "今日无成交（停牌），不可入场"),
    "insufficient_history": ("avoid", "上市不足 126 个交易日，历史不足以判断"),
}


@dataclass
class PickerData:
    as_of: str
    series: dict[str, SymbolSeries]
    names: dict[str, str]
    members: set[str]
    scores: dict[str, Mapping[str, object]]
    market_warnings: dict[str, list[str]]
    price_ratio: dict[str, float]
    screen_results: list[dict[str, object]]
    momentum: dict[str, dict[str, float]]
    sources: dict[str, str]


def load_picker_data(state_path: Path) -> PickerData:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    as_of = str(state["last_successful_as_of"])
    manifests = state["manifests"]
    signal = load_verified_manifest(
        Path(manifests["signal_price"]["processed_manifest"]), expected_layer="processed"
    )
    execution = load_verified_manifest(
        Path(manifests["execution_price"]["processed_manifest"]), expected_layer="processed"
    )
    decision_path = verify_file_reference(state["decision_report"])
    universe_path = verify_file_reference(state["current_universe"])
    membership_path = verify_file_reference(state["membership"])

    series = load_series(signal.artifacts["features.csv"])
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    members = set(
        active_symbols(load_membership_intervals(membership_path), date.fromisoformat(as_of))
    )
    momentum = momentum_table({s: series[s] for s in members if s in series}, as_of)
    warnings: dict[str, list[str]] = defaultdict(list)
    for warning in decision.get("risk_warnings") or []:
        warnings[str(warning["symbol"])].append(f"{warning['action']}: {warning['message']}")
    return PickerData(
        as_of=as_of,
        series=series,
        names=_names(universe_path),
        members=members,
        scores={str(row["symbol"]): row for row in decision.get("scores") or []},
        market_warnings=dict(warnings),
        price_ratio=_price_ratio(series, execution.artifacts["daily.csv"], as_of),
        screen_results=screen(series, as_of, members=members),
        momentum=momentum,
        sources={
            "signal_price_manifest": str(signal.path),
            "execution_price_manifest": str(execution.path),
            "decision_report": str(decision_path),
        },
    )


def load_series(features: Path) -> dict[str, SymbolSeries]:
    rows: dict[str, list[Bar]] = defaultdict(list)
    with features.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            rows[row["symbol"]].append(
                Bar(
                    row["trade_date"],
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    float(row["volume"] or 0.0),
                    row.get("is_suspended") == "true",
                )
            )
    return {s: SymbolSeries(s, sorted(b, key=lambda bar: bar.trade_date)) for s, b in rows.items()}


def universe_payload(data: PickerData, live: LiveContext | None = None) -> list[dict[str, object]]:
    if live is not None:
        try:
            shares = live.all_shares()
        except Exception:  # the full list is optional; fall back to CSI 300 members
            shares = {}
        if shares:
            return [
                {"symbol": s, "name": name, "csi300": s in data.members}
                for s, name in sorted(shares.items())
            ]
    return [
        {"symbol": s, "name": data.names.get(s, ""), "csi300": True} for s in sorted(data.members)
    ]


def _resolve(data: PickerData, query: str, live: LiveContext | None) -> str | None:
    symbol = resolve_symbol(data, query)
    if symbol is None and live is not None:
        symbol = resolve_any(live, query)
    return symbol


def resolve_symbol(data: PickerData, query: str) -> str | None:
    text = query.strip().upper()
    if not text:
        return None
    for symbol in sorted(data.members):
        if text in {symbol, symbol.split(".")[0]}:
            return symbol
    matches = [
        s for s in sorted(data.members) if query.strip() and query.strip() in data.names.get(s, "")
    ]
    return matches[0] if matches else None


def stock_payload(
    data: PickerData,
    query: str,
    live: LiveContext | None = None,
    scoring_v2: Mapping[str, object] | None = None,
    *,
    fresh: bool = False,
) -> dict[str, object]:
    """Live analysis of any A-share; for CSI 300 members, yesterday's point-in-time view is
    attached as pool context. Without a live context (offline, tests) the point-in-time view is
    returned on its own."""
    symbol = _resolve(data, query, live)
    if symbol is None:
        scope = "A 股" if live is not None else "当前 CSI 300 成分"
        return {"error": f"未在{scope}中找到：{query}"}
    pool = pit_stock_payload(data, symbol, scoring_v2) if symbol in data.members else None
    if live is None:
        return pool or {"error": f"未在当前 CSI 300 成分中找到：{query}"}
    payload = live_stock_payload(data, live, symbol, fresh=fresh)
    if pool is None:
        return payload
    if "error" in payload:  # live source down: fall back to yesterday's view, clearly labelled
        pool["verdict"]["notes"].insert(0, f"实时抓取失败，显示交易池数据（截至 {data.as_of} 收盘）")  # type: ignore[index]
        return {**pool, "live_error": payload["error"]}
    return {**payload, "pool_context": _pool_context(pool)}


def pit_stock_payload(
    data: PickerData, symbol: str, scoring_v2: Mapping[str, object] | None = None
) -> dict[str, object]:
    """Yesterday's point-in-time view of a CSI 300 member (the trading pool's data)."""
    item = data.series.get(symbol)
    base = {"symbol": symbol, "name": data.names.get(symbol, ""), "as_of": data.as_of}
    if item is None:
        return {**base, "error": "没有价格数据"}
    analysis = analyze_at(item, data.as_of, data.momentum.get(symbol))
    ratio = data.price_ratio.get(symbol, 1.0)
    rank = next(
        (i + 1 for i, row in enumerate(data.screen_results) if row["symbol"] == symbol), None
    )
    return {
        **base,
        "price_scale": "unadjusted_equivalent",
        "rank": rank,
        "rank_of": len(data.screen_results),
        "analysis": _scaled_analysis(analysis, ratio),
        "chart": _chart(item, data.as_of, analysis, ratio),
        "baseline": _baseline(data.scores.get(symbol)),
        "scoring_v2": snapshot_view(scoring_v2, symbol, data.as_of),
        "market_warnings": data.market_warnings.get(symbol, []),
        "verdict": _verdict(
            analysis, data.scores.get(symbol), data.market_warnings.get(symbol, [])
        ),
        "mode": "csi300",
    }


def _pool_context(pool: Mapping[str, object]) -> dict[str, object]:
    analysis = pool.get("analysis") or {}
    return {
        "as_of": pool.get("as_of"),
        "rank": pool.get("rank"),
        "rank_of": pool.get("rank_of"),
        "state": analysis.get("state"),  # type: ignore[union-attr]
        "headline": (pool.get("verdict") or {}).get("headline"),  # type: ignore[union-attr]
        "baseline": pool.get("baseline"),
        "baseline_pass": (pool.get("verdict") or {}).get("baseline_pass"),  # type: ignore[union-attr]
        "scoring_v2": pool.get("scoring_v2"),
        "market_warnings": pool.get("market_warnings"),
    }


def live_stock_payload(
    data: PickerData, live: LiveContext, symbol: str, *, fresh: bool = False
) -> dict[str, object]:
    """Any A-share, fetched now and analysed with the same rules as the pool."""
    try:
        name = live.all_shares().get(symbol, "") or data.names.get(symbol, "")
    except Exception:  # the list is flaky behind the proxy; members still have a name
        name = data.names.get(symbol, "")
    base = {"symbol": symbol, "name": name, "mode": "live"}
    try:
        result = analyze_live(live, symbol, data.momentum, fresh=fresh)
    except Exception as exc:
        return {**base, "error": f"实时抓取失败：{type(exc).__name__}: {str(exc)[:160]}"}
    analysis = result["analysis"]
    score = result["score"]
    verdict = _verdict(analysis, score, [])
    member = symbol in data.members
    verdict["notes"] = [
        "实时数据（前复权）："
        + ("沪深 300 成分，计数策略仍按交易池的时点数据执行" if member else "非沪深 300 成分")
        + f"；动量分位参照沪深 300 截面（截至 {data.as_of}），未做时点验证",
        *([f"含今日盘中临时 K 线（{result['as_of']}，收盘前会变化）"] if result["provisional"] else []),
        *verdict["notes"],
    ]
    return {
        **base,
        "as_of": result["as_of"],
        "fetched_at": result["fetched_at"],
        "provisional": result["provisional"],
        "csi300": member,
        "price_scale": "qfq",
        "price_source": result["source"],
        "rank": None,
        "rank_of": None,
        "reference": f"沪深300 截面（截至 {data.as_of}）",
        "analysis": analysis,
        "chart": _chart(result["item"], str(result["as_of"]), analysis, 1.0),
        "baseline": _baseline(score),
        "baseline_label": "实时参考分（不进入计数策略）",
        "fundamentals": result["fundamentals"],
        "market_warnings": [],
        "verdict": verdict,
    }


def picks_payload(
    data: PickerData,
    pool_state: Mapping[str, object] | None,
    pool_v2_state: Mapping[str, object] | None = None,
) -> dict[str, object]:
    rows = []
    for row in data.screen_results:
        if row["state"] not in {"trigger", "setup"}:
            continue
        scaled = _scaled_analysis(row, data.price_ratio.get(str(row["symbol"]), 1.0))
        rows.append(
            {
                "symbol": row["symbol"],
                "name": data.names.get(str(row["symbol"]), ""),
                "state": row["state"],
                "close": scaled["close"],
                "stop": scaled["stop"],
                "stop_pct": row["stop_pct"],
                "confluence": row["confluence"],
                "confluence_members": row["confluence_members"],
                "momentum_pct": row["momentum"]["momentum_pct"],  # type: ignore[index]
                "reward_r": row["reward_r"],
                "baseline_total": (data.scores.get(str(row["symbol"])) or {}).get("total"),
            }
        )
    counts: dict[str, int] = defaultdict(int)
    for row in data.screen_results:
        counts[str(row["state"])] += 1
    return {
        "as_of": data.as_of,
        "universe_size": len(data.screen_results),
        "state_counts": dict(counts),
        "candidates": rows,
        "pool": None if pool_state is None else pool_view(data, pool_state),
        "pool_v2": None if pool_v2_state is None else pool_v2_view(data, pool_v2_state),
        "sources": data.sources,
    }


def pool_view(data: PickerData, pool_state: Mapping[str, object]) -> dict[str, object]:
    """Pool state plus names, metrics and hfq mark-to-market for the dashboard."""
    positions = {}
    for symbol, position in dict(pool_state.get("positions") or {}).items():  # type: ignore[arg-type]
        item = data.series.get(symbol)
        marks = [b.close for b in item.bars if b.trade_date <= data.as_of] if item else []
        value = float(position["shares"]) * marks[-1] if marks else None
        positions[symbol] = {
            **position,
            "name": data.names.get(symbol, ""),
            "unrealized": None if value is None else value / float(position["cost"]) - 1.0,
        }
    return {
        "as_of": pool_state.get("as_of"),
        "pool": [
            {**row, "name": data.names.get(str(row["symbol"]), "")}
            for row in pool_state.get("pool") or []  # type: ignore[union-attr]
        ],
        "pending": list(pool_state.get("pending") or []),  # type: ignore[arg-type]
        "positions": positions,
        "closed_trades": list(pool_state.get("closed_trades") or [])[-20:],  # type: ignore[arg-type]
        "metrics": pool_metrics(pool_state),
        "stale": pool_state.get("as_of") != data.as_of,
    }


def pool_v2_view(data: PickerData, pool_state: Mapping[str, object]) -> dict[str, object]:
    """v2 book with watchlist ages, each position's R multiple and which exit rules are armed."""
    book = dict(pool_state["book"])  # type: ignore[arg-type]
    positions = {}
    for symbol, position in dict(book["positions"]).items():
        item = data.series.get(symbol)
        index = None
        if item is not None:
            dates = [i for d, i in item.index_by_date.items() if d <= data.as_of]
            index = max(dates) if dates else None
        status = (
            {}
            if item is None or index is None
            else position_status(
                position,
                close=item.bars[index].close,
                ema9=item.ema9[index],
                ema21=item.ema21[index],
            )
        )
        positions[symbol] = {**position, **status, "name": data.names.get(symbol, "")}
    return {
        "as_of": pool_state.get("as_of"),
        "watchlist": [
            {**row, "name": data.names.get(str(row["symbol"]), "")}
            for row in pool_state.get("watchlist") or []  # type: ignore[union-attr]
        ],
        "pending": list(book["pending"]),
        "positions": positions,
        "closed_trades": list(book["closed_trades"])[-20:],
        "metrics": pool_v2_metrics(pool_state),
        "stale": pool_state.get("as_of") != data.as_of,
    }


def intraday_monitor_view(
    data: PickerData,
    plan: Mapping[str, object] | None,
    triggers: Mapping[str, object] | None,
    comparison: Mapping[str, object] | None,
) -> dict[str, object] | None:
    """Latest intraday plan with its zones (unadjusted) and any triggers recorded so far."""
    if plan is None:
        return None
    recorded = dict((triggers or {}).get("triggers") or {})  # type: ignore[arg-type]
    names = [
        {
            **entry,
            "name": data.names.get(str(entry["symbol"]), ""),
            "trigger": recorded.get(str(entry["symbol"])),
        }
        for entry in plan["names"]  # type: ignore[union-attr]
    ]
    summary = None
    if comparison is not None:
        summary = {
            key: comparison.get(key)
            for key in (
                "as_of", "plan_days", "intraday_entries", "daily_entries", "both_entered",
                "mean_entry_gap", "intraday_closed", "daily_closed",
            )
        }
    return {
        "date": plan["date"],
        "reference_session": plan["reference_session"],
        "names": names,
        "polls": (triggers or {}).get("polls", 0),
        "last_poll_at": (triggers or {}).get("last_poll_at"),
        "finalized": bool((triggers or {}).get("finalized")),
        "errors": dict((triggers or {}).get("errors") or {}),  # type: ignore[arg-type]
        "comparison": summary,
    }


def _verdict(
    analysis: Mapping[str, object],
    score: Mapping[str, object] | None,
    warnings: list[str],
) -> dict[str, object]:
    level, headline = VERDICTS.get(str(analysis["state"]), ("avoid", "数据不足，无法判断"))
    policy = approved_paper_policy()
    baseline_pass = bool(
        score
        and float(score["total"]) >= float(policy["buy_threshold"])  # type: ignore[arg-type]
        and float(score["confidence"]) >= float(policy["minimum_score_confidence"])  # type: ignore[arg-type]
    )
    reasons = [str(check["detail"]) for check in analysis.get("checks", []) if not check["passed"]]  # type: ignore[union-attr]
    notes = []
    if baseline_pass:
        notes.append("多因子基线同时通过 70 分 / 0.8 置信度门槛")
    elif score:
        notes.append(f"多因子基线 {float(score['total']):.1f} 分，未达 70 分门槛")
    if analysis["state"] == "trigger":
        notes.append("A 股 T+1：入场当日无法按日内低点止损，隔夜风险需自行承担")
    notes.extend(warnings)
    return {
        "level": level,
        "headline": headline,
        "baseline_pass": baseline_pass,
        "failed_checks": reasons,
        "notes": notes,
        "disclaimer": "研究用途，不构成投资建议；系统不下单。",
    }


def _baseline(score: Mapping[str, object] | None) -> dict[str, object] | None:
    if not score:
        return None
    return {
        "total": score["total"],
        "confidence": score["confidence"],
        "components": score.get("components"),
    }


def _scaled_analysis(analysis: Mapping[str, object], ratio: float) -> dict[str, object]:
    scaled = dict(analysis)
    for key in ("close", "low", "stop"):
        if isinstance(scaled.get(key), (int, float)):
            scaled[key] = round(float(scaled[key]) * ratio, 3)  # type: ignore[arg-type]
    for key in ("supports", "ema"):
        if isinstance(scaled.get(key), Mapping):
            scaled[key] = {k: round(float(v) * ratio, 3) for k, v in dict(scaled[key]).items()}  # type: ignore[arg-type]
    if isinstance(scaled.get("zone"), Mapping):
        scaled["zone"] = {k: round(float(v) * ratio, 3) for k, v in dict(scaled["zone"]).items()}  # type: ignore[arg-type]
    return scaled


def _chart(
    item: SymbolSeries, as_of: str, analysis: Mapping[str, object], ratio: float
) -> dict[str, object]:
    end = item.index_by_date.get(as_of)
    if end is None:
        end = len(item.bars) - 1
    start = max(0, end - CHART_SESSIONS + 1)
    window = item.bars[start : end + 1]

    def scale(values: list[float | None]) -> list[float | None]:
        return [None if v is None else round(v * ratio, 3) for v in values]

    lines: dict[str, list[float | None]] = {
        "ema9": scale(item.ema9[start : end + 1]),
        "ema21": scale(item.ema21[start : end + 1]),
        "ema50": scale(item.ema50[start : end + 1]),
    }
    anchors = analysis.get("anchors") or {}
    for name in ("swing_low", "swing_high"):
        anchor_date = anchors.get(name)  # type: ignore[union-attr]
        anchor = item.index_by_date.get(str(anchor_date)) if anchor_date else None
        if anchor is not None:
            values = [None] * len(window)
            for offset, i in enumerate(range(start, end + 1)):
                if i >= anchor:
                    values[offset] = item.avwap(anchor, i)
            lines[f"avwap_{name}"] = scale(values)
    return {
        "dates": [bar.trade_date for bar in window],
        "ohlc": [
            [
                round(b.open * ratio, 3),
                round(b.high * ratio, 3),
                round(b.low * ratio, 3),
                round(b.close * ratio, 3),
            ]
            for b in window
        ],
        "volume": [b.volume for b in window],
        "lines": lines,
    }


def _price_ratio(series: Mapping[str, SymbolSeries], daily: Path, as_of: str) -> dict[str, float]:
    """Unadjusted/hfq close ratio on each symbol's latest common session up to ``as_of``."""
    unadjusted: dict[str, dict[str, float]] = defaultdict(dict)
    with daily.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["trade_date"] <= as_of and row.get("close"):
                unadjusted[row["symbol"]][row["trade_date"]] = float(row["close"])
    ratios = {}
    for symbol, item in series.items():
        closes = unadjusted.get(symbol, {})
        for bar in reversed(item.bars):
            if bar.trade_date <= as_of and bar.trade_date in closes and bar.close > 0:
                ratios[symbol] = closes[bar.trade_date] / bar.close
                break
    return ratios


def _names(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["symbol"]: row.get("name", "") for row in csv.DictReader(handle)}


def research_payload(
    data: PickerData,
    query: str,
    *,
    cache_dir: Path | None,
    jev_record_dir: Path | None,
    today: date | None = None,
    fetchers: Mapping[str, object] | None = None,
    live: LiveContext | None = None,
    global_fetchers: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Multi-source information, event NLP, research consensus and financial trend for one stock."""
    symbol = _resolve(data, query, live)
    if symbol is None:
        return {"error": f"未找到：{query}"}
    day = today or date.today()
    intel, name, world, nlp = _gather(
        data, symbol, day, cache_dir=cache_dir, fetchers=fetchers, live=live,
        global_fetchers=global_fetchers,
    )
    research = {
        "symbol": symbol,
        "name": name,
        "fetched_at": intel["fetched_at"],
        "sources": {**intel["sources"], **(world["sources"] if world else {})},  # type: ignore[dict-item]
        "global": None if world is None else {
            "industry": world["industry"],
            "industry_keywords": world["industry_keywords"],
            "overseas": world["overseas"],
        },
        "nlp": {key: value for key, value in nlp.items() if key != "items"},
        # newest first across company and global sources, so global flashes are not cut off
        "items": sorted(nlp["items"], key=lambda i: str(i.get("published_at", "")), reverse=True)[:80],
        "consensus": research_consensus(intel["items"], today=day),  # type: ignore[arg-type]
        "financials": intel["financials"],
        "financial_trend": financial_trend(intel["financials"]),  # type: ignore[arg-type]
        "comment_scores": intel["comment_scores"],
        "jev": config_status(),
        "events_llm": _events_llm_status(),
    }
    if cache_dir is not None and research["events_llm"].get("configured"):  # type: ignore[union-attr]
        saved = event_llm.cached_result(
            nlp["items"],  # type: ignore[arg-type]
            name=name.replace(" ", ""),
            symbol=symbol,
            model=str(research["events_llm"]["model"]),  # type: ignore[index]
            record_dir=cache_dir / "event_llm",
            today=day,
        )
        if saved is not None:
            research["events_llm_result"] = saved
    if cache_dir is not None:
        research["events_llm_spend"] = jev_spend(cache_dir / "event_llm", today=day)
    packet = jev_packet(stock_payload(data, symbol, live), research)
    research["jev_packet_sha256"] = hashlib.sha256(
        json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    if jev_record_dir is not None:
        model = str(research["jev"].get("model", ""))  # type: ignore[union-attr]
        packet_sha = str(research["jev_packet_sha256"])
        exact = jev_record_dir / data.as_of / record_name(symbol, packet_sha, model)
        saved = sorted(
            (jev_record_dir / data.as_of).glob(
                f"{symbol}-{packet_sha[:12]}-{questions_sha()[:8]}-*.json"
            ),
            key=lambda path: path.stat().st_mtime,
        )
        record = (
            exact
            if model and exact.exists()
            else (None if model else (saved[-1] if saved else None))
        )
        if record is not None:
            research["jev_record"] = {
                **json.loads(record.read_text(encoding="utf-8")),
                "cached": True,
            }
        research["jev_spend"] = jev_spend(jev_record_dir, today=day)
    return research


def events_llm_payload(
    data: PickerData,
    query: str,
    *,
    cache_dir: Path | None,
    client: LlmClient | None = None,
    today: date | None = None,
    fetchers: Mapping[str, object] | None = None,
    live: LiveContext | None = None,
    global_fetchers: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Label the items the keyword rules left untagged with a chat model (advisory, cached daily)."""
    symbol = _resolve(data, query, live)
    if symbol is None:
        return {"error": f"未找到：{query}"}
    day = today or date.today()
    _, name, _, nlp = _gather(
        data, symbol, day, cache_dir=cache_dir, fetchers=fetchers, live=live,
        global_fetchers=global_fetchers,
    )
    name = name.replace(" ", "")
    try:
        active = client or event_llm.client_from_env()
    except event_llm.EventLlmNotConfigured as exc:
        return {"error": str(exc)}
    record_dir = None if cache_dir is None else cache_dir / "event_llm"
    result = event_llm.classify_events(
        nlp["items"],  # type: ignore[arg-type]
        name=name,
        symbol=symbol,
        client=active,
        record_dir=record_dir,
        today=day,
    )
    if record_dir is not None:
        result["spend"] = jev_spend(record_dir, today=day)
    return result


def _gather(
    data: PickerData,
    symbol: str,
    day: date,
    *,
    cache_dir: Path | None,
    fetchers: Mapping[str, object] | None,
    live: LiveContext | None,
    global_fetchers: Mapping[str, object] | None,
) -> tuple[dict[str, object], str, dict[str, object] | None, dict[str, object]]:
    """Company sources plus, with a live context, global flashes and overseas moves; one NLP pass."""
    intel = collect_stock_intel(symbol, today=day, cache_dir=cache_dir, fetchers=fetchers)  # type: ignore[arg-type]
    name = data.names.get(symbol) or ""
    if not name and live is not None:
        try:
            name = live.all_shares().get(symbol, "")
        except Exception:  # the list is flaky behind the proxy
            name = ""
    world = None
    if live is not None:
        world = collect_global_intel(
            name=name.replace(" ", ""),
            symbol=symbol,
            industry=stock_industry(live, symbol, _local_industries()),
            fetchers=global_fetchers,  # type: ignore[arg-type]
        )
    items = [*intel["items"], *(world["items"] if world else [])]  # type: ignore[misc]
    nlp = analyze_items(items, today=day, name=name.replace(" ", ""), symbol=symbol)
    return intel, name, world, nlp


INDUSTRY_TABLE = Path(__file__).resolve().parents[3] / "data/raw/industry/sw_industry_cninfo.csv"
_INDUSTRIES: dict[str, str] | None = None


def _local_industries() -> dict[str, str]:
    """Latest Shenwan level-1 industry per CSI 300 member from the factor lab's table."""
    global _INDUSTRIES
    if _INDUSTRIES is None:
        latest: dict[str, tuple[str, str]] = {}
        if INDUSTRY_TABLE.exists():
            with INDUSTRY_TABLE.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    if row.get("sw_level1") and (
                        row["symbol"] not in latest or row["change_date"] > latest[row["symbol"]][0]
                    ):
                        latest[row["symbol"]] = (row["change_date"], row["sw_level1"])
        _INDUSTRIES = {symbol: industry for symbol, (_, industry) in latest.items()}
    return _INDUSTRIES


def _events_llm_status() -> dict[str, object]:
    try:
        client = event_llm.client_from_env()
    except event_llm.EventLlmNotConfigured as exc:
        return {"configured": False, "reason": str(exc)}
    return {"configured": True, "model": client.model}


def jev_payload(
    data: PickerData,
    query: str,
    *,
    cache_dir: Path | None,
    jev_record_dir: Path | None,
    client: LlmClient | JevDecisionClient | None = None,
    today: date | None = None,
    fetchers: Mapping[str, object] | None = None,
    live: LiveContext | None = None,
) -> dict[str, object]:
    research = research_payload(
        data,
        query,
        cache_dir=cache_dir,
        jev_record_dir=jev_record_dir,
        today=today,
        fetchers=fetchers,
        live=live,
    )
    if "error" in research:
        return research
    if "jev_record" in research:
        return {**research["jev_record"], "cached": True, "jev_spend": research.get("jev_spend")}  # type: ignore[dict-item]
    active = client or client_from_env()
    if active is None:
        return {
            "error": "Jev 未配置：在 .env 设置 JEV_MODEL=Jev 1.14 + OPENROUTER_API_KEY（或 DEEPSEEK_API_KEY）后重启看板"
        }
    packet = jev_packet(stock_payload(data, str(research["symbol"]), live), research)
    record = ask_jev(packet, client=active, record_dir=jev_record_dir)
    if jev_record_dir is not None:
        record["jev_spend"] = jev_spend(jev_record_dir, today=today or date.today())
    return record


def jev_spend(record_dir: Path, *, today: date) -> dict[str, object]:
    """Sum recorded model call costs: today (local calendar date of the call) and all time.
    Used for both Jev records and LLM-assist records. DeepSeek calls saved before costs were
    recorded are priced from their token counts, all input treated as a cache miss."""
    totals = {
        "today_calls": 0,
        "today_cost": 0.0,
        "total_calls": 0,
        "total_cost": 0.0,
        "unpriced_calls": 0,
    }
    for path in record_dir.glob("*/*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        usage = record.get("usage") or {}
        cost = usage.get("cost")
        if cost is None and usage.get("input_tokens") is not None:
            moment = _timestamp(str(record.get("created_at", "")))
            cost = moment and deepseek_cost(
                str(record.get("model", "")),
                {
                    "prompt_tokens": usage.get("input_tokens"),
                    "completion_tokens": usage.get("output_tokens"),
                },
                moment,
            )
        is_today = _local_date(str(record.get("created_at", ""))) == today
        totals["total_calls"] += 1
        totals["today_calls"] += int(is_today)
        if isinstance(cost, (int, float)):
            totals["total_cost"] += float(cost)
            totals["today_cost"] += float(cost) if is_today else 0.0
        else:
            totals["unpriced_calls"] += 1
    return totals


def jev_packet(stock: Mapping[str, object], research: Mapping[str, object]) -> dict[str, object]:
    """The only facts Jev sees: compact, dated, and identical for identical inputs."""
    analysis = stock.get("analysis") or {}
    baseline = stock.get("baseline") or {}
    items = [i for i in research.get("items", []) if i.get("kind") != "research"]  # type: ignore[union-attr]
    newest = sorted(items, key=lambda i: str(i.get("published_at")), reverse=True)
    focus = sorted(newest, key=lambda i: not i.get("tags"))[:15]  # tagged first, newest first
    return {
        "symbol": stock.get("symbol"),
        "name": stock.get("name"),
        "as_of": stock.get("as_of"),
        "information_date": str(research.get("fetched_at", ""))[:10],
        "technical_level": (stock.get("verdict") or {}).get("level"),  # type: ignore[union-attr]
        "technical": {
            "state": analysis.get("state"),  # type: ignore[union-attr]
            "checks": [
                {"label": c["label"], "passed": c["passed"], "detail": c["detail"]}
                for c in analysis.get("checks", [])  # type: ignore[union-attr]
            ],
        },
        "baseline": {
            "total": baseline.get("total"),  # type: ignore[union-attr]
            "confidence": baseline.get("confidence"),  # type: ignore[union-attr]
            "components": {
                k: v.get("score")
                for k, v in dict(baseline.get("components") or {}).items()  # type: ignore[union-attr]
            },
        },
        "market_warnings": stock.get("market_warnings"),
        "nlp": {k: research["nlp"][k] for k in ("sentiment", "label", "event_counts")},  # type: ignore[index]
        "recent_items": [
            {
                "date": str(i.get("published_at", ""))[:10],
                "kind": i.get("kind"),
                "source": i.get("source"),
                "title": str(i.get("title", ""))[:90],
                "tags": i.get("tags"),
            }
            for i in focus
        ],
        "research_consensus": research.get("consensus"),
        "financials": [
            {
                "报告期": p.get("period"),
                "营收同比": _signed_pct(p.get("revenue_yoy")),
                "净利润同比": _signed_pct(p.get("net_profit_yoy")),
                "扣非净利润同比": _signed_pct(p.get("deducted_profit_yoy")),
                "ROE（报告期，未年化）": _signed_pct(p.get("roe")),
                "销售净利率": _signed_pct(p.get("net_margin")),
            }
            for p in research.get("financials", [])[:6]  # type: ignore[union-attr]
        ],
        "financial_flags": [
            f["text"] for f in research.get("financial_trend", {}).get("flags", [])
        ],  # type: ignore[union-attr]
    }


def _signed_pct(value: object) -> str | None:
    """Readable percentages for model input: 0.42 -> '+42.0%' (raw ratios get misread as 0.42%)."""
    return None if not isinstance(value, (int, float)) else f"{float(value):+.1%}"


def _local_date(timestamp: str) -> date | None:
    moment = _timestamp(timestamp)
    return moment.astimezone().date() if moment else None


def _timestamp(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
