"""Read-only data layer for the desk's stock-picker page.

Everything comes from artifacts the canonical pipeline state already hash-binds: the processed
signal-price (hfq) and execution-price (unadjusted) snapshots, the decision report, the current
constituent list and the membership history. Chart levels are shown on the current unadjusted
price scale (hfq level x latest unadjusted/hfq close ratio), like a forward-adjusted chart.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping

from fintech_quant.data.historical_universe import active_symbols, load_membership_intervals
from fintech_quant.data.manifest_chain import load_verified_manifest
from fintech_quant.execution.paper_evidence import approved_paper_policy, verify_file_reference
from fintech_quant.research.momentum_pool import pool_metrics
from fintech_quant.research.momentum_setup import (
    Bar,
    SymbolSeries,
    analyze_at,
    momentum_table,
    screen,
)


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


def universe_payload(data: PickerData) -> list[dict[str, str]]:
    return [{"symbol": s, "name": data.names.get(s, "")} for s in sorted(data.members)]


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


def stock_payload(data: PickerData, query: str) -> dict[str, object]:
    symbol = resolve_symbol(data, query)
    if symbol is None:
        return {"error": f"未在当前 CSI 300 成分中找到：{query}"}
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
        "market_warnings": data.market_warnings.get(symbol, []),
        "verdict": _verdict(
            analysis, data.scores.get(symbol), data.market_warnings.get(symbol, [])
        ),
    }


def picks_payload(data: PickerData, pool_state: Mapping[str, object] | None) -> dict[str, object]:
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
