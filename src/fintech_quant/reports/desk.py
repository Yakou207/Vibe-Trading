"""Read-only "trading desk" view of the CSI 300 paper-evidence chain.

Each desk agent is a deterministic pipeline stage that already exists in the
post-close cycle (data gate, scoring, risk veto, sizing, execution, drawdown
control, audit). The snapshot only reads immutable cycle artifacts and never
mutates the paper account or pipeline state.
"""

from __future__ import annotations

import csv
import html
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from fintech_quant.data.run_artifacts import sha256_file


SCHEMA_VERSION = 1
REQUIRED_SESSIONS = 40
REQUIRED_CALENDAR_DAYS = 56
CANDIDATE_LIMIT = 12
TEMPLATE_PATH = Path(__file__).with_name("desk_template.html")
COMPONENT_ORDER = ("fundamental", "technical", "capital_flow", "sentiment")
CYCLE_FILES = ("cycle_manifest.json", "decision_report.json", "paper_report.json")


def build_desk_snapshot(
    cycle_root: Path,
    *,
    pnl_curve: Path | None = None,
    quotes: Sequence[Mapping[str, object]] | None = None,
    quotes_status: str | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    cycle_dir = latest_complete_cycle(cycle_root)
    manifest = _load_json(cycle_dir / "cycle_manifest.json")
    decision = _load_json(cycle_dir / "decision_report.json")
    paper = _load_json(cycle_dir / "paper_report.json")
    validation_path = cycle_dir / "validation_report.json"
    validation = _load_json(validation_path) if validation_path.exists() else {}
    benchmark = _load_benchmark(cycle_dir / "csi300_market_state.csv")
    names = _load_names(cycle_dir / "current_universe.csv")
    targets = _load_targets(cycle_dir / "targets.csv")

    policy = _mapping(manifest.get("policy"))
    account = _mapping(paper.get("account"))
    nav = _mapping(paper.get("nav"))
    quote_map = {str(row["symbol"]): dict(row) for row in quotes or ()}
    as_of = str(manifest["as_of"])

    funnel = _funnel(decision, policy, targets)
    candidates = _candidates(decision, policy, targets, names, quote_map)
    positions = _positions(account, names, quote_map)
    timeline = _timeline(cycle_root, validation, benchmark, as_of)
    gates = _gates(validation)
    header = _header(manifest, validation, account, nav, positions)
    drawdown = _drawdown(account, nav, policy)
    agents = _agents(
        manifest=manifest,
        decision=decision,
        paper=paper,
        validation=validation,
        policy=policy,
        funnel=funnel,
        targets=targets,
        drawdown=drawdown,
        header=header,
    )
    snapshot: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "as_of": as_of,
        "mode": "intraday" if quote_map else "post_close",
        "quotes_status": quotes_status or ("live" if quote_map else "off"),
        "cycle": {
            "path": str(cycle_dir),
            "manifest_sha256": sha256_file(cycle_dir / "cycle_manifest.json"),
            "git_sha": manifest.get("git_sha"),
            "parent_sha256": _mapping(manifest.get("evidence_parent")).get("sha256"),
        },
        "header": header,
        "agents": agents,
        "events": [event for agent in agents for event in agent["log"]],
        "funnel": funnel,
        "policy": _policy_rows(policy, decision),
        "gates": gates,
        "candidates": candidates,
        "targets": [
            {**row, "name": names.get(row["symbol"], ""), "quote": _quote(quote_map, row["symbol"])}
            for row in targets
        ],
        "positions": positions,
        "blocked_orders": list(paper.get("blocked_orders") or []),
        "trades": list(paper.get("trades") or []),
        "drawdown": drawdown,
        "timeline": timeline,
        "paper_curve": _paper_curve(
            account, benchmark, str(_mapping(validation.get("window")).get("anchor_date") or "")
        ),
        "backtest_curve": _backtest_curve(pnl_curve),
    }
    return snapshot


def latest_complete_cycle(cycle_root: Path) -> Path:
    complete = [
        path
        for path in sorted(cycle_root.iterdir())
        if path.is_dir()
        and _is_date(path.name)
        and all((path / name).exists() for name in CYCLE_FILES)
    ]
    if not complete:
        raise FileNotFoundError(f"no complete paper cycle under {cycle_root}")
    return complete[-1]


def cycle_fingerprint(cycle_root: Path, extra: Sequence[Path] = ()) -> tuple[object, ...]:
    """Cheap change detector for the live server: names and mtimes only."""
    entries: list[object] = []
    for path in sorted(cycle_root.iterdir()):
        if path.is_dir():
            entries.append(
                (
                    path.name,
                    tuple(
                        sorted((child.name, child.stat().st_mtime_ns) for child in path.iterdir())
                    ),
                )
            )
    for path in extra:
        entries.append((str(path), path.stat().st_mtime_ns if path.exists() else None))
    return tuple(entries)


def watched_symbols(snapshot: Mapping[str, object]) -> list[str]:
    symbols = {str(row["symbol"]) for row in snapshot.get("targets", [])}  # type: ignore[union-attr]
    symbols.update(str(row["symbol"]) for row in snapshot.get("positions", []))  # type: ignore[union-attr]
    symbols.update(str(row["symbol"]) for row in snapshot.get("candidates", []))  # type: ignore[union-attr]
    return sorted(symbols)


def render_desk_html(snapshot: Mapping[str, object], *, live: bool) -> str:
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).replace(
        "<", "\\u003c"
    )
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    return (
        template.replace("__DESK_SNAPSHOT__", payload)
        .replace("__DESK_LIVE__", "true" if live else "false")
        .replace("__DESK_TITLE__", html.escape(f"CSI 300 Desk · {snapshot['as_of']}"))
    )


def _header(
    manifest: Mapping[str, object],
    validation: Mapping[str, object],
    account: Mapping[str, object],
    nav: Mapping[str, object],
    positions: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    metrics = _mapping(validation.get("metrics"))
    window = _mapping(validation.get("window"))
    history = list(account.get("nav_history") or [])
    initial = float(history[0]["equity"]) if history else float(nav.get("equity") or 0.0)
    equity = float(nav.get("equity") or 0.0)
    live_marked = [row for row in positions if row.get("mark_source") == "live_quote"]
    live_equity = None
    if live_marked:
        live_equity = round(
            float(account.get("cash") or 0.0)
            + sum(float(row["market_value"]) for row in positions),
            2,
        )
    return {
        "initial_equity": initial,
        "equity": equity,
        "live_equity": live_equity,
        "cash": float(account.get("cash") or 0.0),
        "paper_return": metrics.get("paper_return"),
        "benchmark_return": metrics.get("benchmark_return"),
        "excess_return": metrics.get("excess_return"),
        "valid_sessions": int(metrics.get("valid_sessions") or 0),
        "required_sessions": REQUIRED_SESSIONS,
        "calendar_days": int(window.get("calendar_days") or 0),
        "required_calendar_days": REQUIRED_CALENDAR_DAYS,
        "status": validation.get("status", "NO_AUDIT"),
        "live_trading_authorized": bool(validation.get("live_trading_authorized", False)),
        "strategy": _mapping(manifest.get("policy")).get("strategy"),
        "pending_signal_date": account.get("pending_signal_date"),
    }


def _funnel(
    decision: Mapping[str, object],
    policy: Mapping[str, object],
    targets: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    scores = list(decision.get("scores") or [])
    buy = float(policy.get("buy_threshold", 70.0))
    min_conf = float(policy.get("minimum_score_confidence", 0.8))
    health = bool(decision.get("data_health_passed"))
    vetoed = _vetoed_symbols(decision)
    above = [row for row in scores if float(row["total"]) >= buy]
    confident = [row for row in above if float(row["confidence"]) >= min_conf]
    cleared = [row for row in confident if row["symbol"] not in vetoed]
    return [
        {
            "stage": "members",
            "label": "CSI 300 成分股",
            "count": int(decision.get("active_member_count") or len(scores)),
        },
        {"stage": "data_gate", "label": "数据健康门禁", "count": len(scores) if health else 0},
        {"stage": "score_gate", "label": f"总分 ≥ {buy:g}", "count": len(above)},
        {"stage": "confidence_gate", "label": f"置信度 ≥ {min_conf:g}", "count": len(confident)},
        {"stage": "risk_veto", "label": "风险规则未否决", "count": len(cleared)},
        {"stage": "targets", "label": "目标仓位 (D+1 开盘)", "count": len(targets)},
    ]


def _vetoed_symbols(decision: Mapping[str, object]) -> set[str]:
    return {
        str(warning["symbol"])
        for warning in decision.get("risk_warnings") or []
        if str(warning.get("action")) in {"reduce", "exit", "block", "veto"}
    }


def _candidates(
    decision: Mapping[str, object],
    policy: Mapping[str, object],
    targets: Sequence[Mapping[str, object]],
    names: Mapping[str, str],
    quote_map: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    buy = float(policy.get("buy_threshold", 70.0))
    min_conf = float(policy.get("minimum_score_confidence", 0.8))
    vetoed = _vetoed_symbols(decision)
    target_weights = {row["symbol"]: row["target_weight"] for row in targets}
    ranked = sorted(
        decision.get("scores") or [], key=lambda row: (-float(row["total"]), row["symbol"])
    )
    rows = []
    for score in ranked[:CANDIDATE_LIMIT]:
        symbol = str(score["symbol"])
        components = _mapping(score.get("components"))
        rows.append(
            {
                "symbol": symbol,
                "name": names.get(symbol, ""),
                "total": float(score["total"]),
                "confidence": float(score["confidence"]),
                "components": {
                    key: {
                        "score": float(_mapping(components.get(key)).get("score", 0.0)),
                        "max": float(_mapping(components.get(key)).get("max_score", 0.0)),
                        "reasons": list(_mapping(components.get(key)).get("reasons") or []),
                    }
                    for key in COMPONENT_ORDER
                },
                "passes_score": float(score["total"]) >= buy,
                "passes_confidence": float(score["confidence"]) >= min_conf,
                "vetoed": symbol in vetoed,
                "target_weight": target_weights.get(symbol),
                "quote": _quote(quote_map, symbol),
            }
        )
    return rows


def _positions(
    account: Mapping[str, object],
    names: Mapping[str, str],
    quote_map: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    rows = []
    for symbol, position in sorted(_mapping(account.get("positions")).items()):
        shares = int(position["shares"])
        cost = float(position["cost_basis"])
        quote = _quote(quote_map, symbol)
        price = float(quote["price"]) if quote else cost
        rows.append(
            {
                "symbol": symbol,
                "name": names.get(symbol, ""),
                "shares": shares,
                "cost_basis": cost,
                "price": price,
                "market_value": round(shares * price, 2),
                "unrealized_pnl": round(shares * (price - cost), 2),
                "mark_source": "live_quote" if quote else "cost_basis",
                "last_buy_date": position.get("last_buy_date"),
            }
        )
    return rows


def _drawdown(
    account: Mapping[str, object], nav: Mapping[str, object], policy: Mapping[str, object]
) -> dict[str, object]:
    state = _mapping(account.get("drawdown_control_state"))
    peak = float(state.get("actual_peak") or nav.get("equity") or 0.0)
    equity = float(nav.get("equity") or 0.0)
    current = 0.0 if peak <= 0 else max(0.0, 1.0 - equity / peak)
    return {
        "regime": state.get("regime", "normal"),
        "current": round(current, 6),
        "peak": peak,
        "reduce": float(policy.get("drawdown_reduce", 0.08)),
        "liquidate": float(policy.get("drawdown_liquidate", 0.09)),
        "limit": float(policy.get("drawdown_validation_limit", 0.1)),
        "exposure_multiplier": float(nav.get("exposure_multiplier") or 1.0),
        "transitions": list(state.get("transitions") or []),
    }


def _timeline(
    cycle_root: Path,
    validation: Mapping[str, object],
    benchmark: Sequence[tuple[str, float]],
    as_of: str,
) -> list[dict[str, str]]:
    anchor = str(_mapping(validation.get("window")).get("anchor_date") or "")
    sessions = [trade_date for trade_date, _ in benchmark if anchor < trade_date <= as_of]
    rows = []
    for trade_date in sessions:
        path = cycle_root / trade_date
        if path.is_dir() and all((path / name).exists() for name in CYCLE_FILES):
            status = "complete"
        elif path.is_dir():
            status = "partial"
        else:
            status = "missing"
        rows.append({"date": trade_date, "status": status})
    return rows


def _gates(validation: Mapping[str, object]) -> list[dict[str, object]]:
    return [
        {
            "name": name,
            "observed": gate.get("observed"),
            "required": gate.get("required"),
            "passed": bool(gate.get("passed")),
        }
        for name, gate in sorted(_mapping(validation.get("gates")).items())
    ]


def _policy_rows(
    policy: Mapping[str, object], decision: Mapping[str, object]
) -> list[dict[str, object]]:
    rows = [
        {"group": "policy", "name": key, "value": value} for key, value in sorted(policy.items())
    ]
    rows.extend(
        {"group": "risk_limits", "name": key, "value": value}
        for key, value in sorted(_mapping(decision.get("risk_limits")).items())
    )
    return rows


def _paper_curve(
    account: Mapping[str, object], benchmark: Sequence[tuple[str, float]], anchor: str
) -> dict[str, object]:
    """Normalize CSI 300 to paper equity at the audit anchor so both lines share the evidence window."""
    history = [row for row in account.get("nav_history") or [] if str(row["trade_date"]) >= anchor]
    shadow = {
        str(row["trade_date"]): float(row["equity"])
        for row in account.get("shadow_nav_history") or []
    }
    closes = dict(benchmark)
    dates = [str(row["trade_date"]) for row in history if str(row["trade_date"]) in closes]
    if not dates:
        return {"dates": [], "equity": [], "shadow_equity": [], "csi300": []}
    by_date = {str(row["trade_date"]): float(row["equity"]) for row in history}
    base_equity = by_date[dates[0]]
    base_close = closes[dates[0]]
    return {
        "dates": dates,
        "equity": [by_date[day] for day in dates],
        "shadow_equity": [shadow.get(day) for day in dates],
        "csi300": [round(base_equity * closes[day] / base_close, 2) for day in dates],
    }


def _backtest_curve(path: Path | None) -> dict[str, object] | None:
    if path is None or not path.exists():
        return None
    payload = _load_json(path)
    series = _mapping(payload.get("series"))
    return {
        "dates": list(payload.get("dates") or []),
        "sha256": sha256_file(path),
        "series": {
            key: {
                "label": _mapping(value).get("label", key),
                "equity": list(_mapping(value).get("equity") or []),
            }
            for key, value in series.items()
        },
    }


def _agents(
    *,
    manifest: Mapping[str, object],
    decision: Mapping[str, object],
    paper: Mapping[str, object],
    validation: Mapping[str, object],
    policy: Mapping[str, object],
    funnel: Sequence[Mapping[str, object]],
    targets: Sequence[Mapping[str, object]],
    drawdown: Mapping[str, object],
    header: Mapping[str, object],
) -> list[dict[str, object]]:
    as_of = str(manifest["as_of"])
    counts = {row["stage"]: row["count"] for row in funnel}
    health = _mapping(decision.get("data_health"))
    metrics = _mapping(health.get("metrics"))
    risk = _mapping(decision.get("risk_summary"))
    warnings = int(risk.get("total_warnings") or 0)
    trades = list(paper.get("trades") or [])
    blocked = list(paper.get("blocked_orders") or [])
    gross = sum(float(row["target_weight"]) for row in targets)
    ranked = sorted(decision.get("scores") or [], key=lambda row: -float(row["total"]))
    top = ranked[0] if ranked else None
    failures = list(validation.get("failures") or [])
    dd_regime = str(drawdown["regime"])
    health_ok = bool(health.get("passed"))

    def agent(
        agent_id: str, role: str, status: str, metric: str, progress: float, lines: Sequence[str]
    ) -> dict[str, object]:
        level = {"ok": "info", "alert": "warn", "blocked": "error", "idle": "info"}[status]
        return {
            "id": agent_id,
            "role": role,
            "status": status,
            "metric": metric,
            "progress": max(0.0, min(1.0, progress)),
            "headline": lines[0],
            "log": [
                {"date": as_of, "agent": agent_id, "level": level, "text": text} for text in lines
            ],
        }

    rule_text = ", ".join(
        f"{name}×{count}" for name, count in sorted(_mapping(risk.get("by_rule")).items())
    )
    return [
        agent(
            "CRAWLER",
            "数据采集 · 健康门禁",
            "ok" if health_ok else "blocked",
            f"{float(metrics.get('price_coverage') or 0):.2%}",
            float(metrics.get("price_coverage") or 0),
            [
                f"数据门禁{'通过' if health_ok else '未通过'}：价格覆盖 {float(metrics.get('price_coverage') or 0):.2%}，"
                f"基本面 {float(metrics.get('fundamental_coverage') or 0):.2%}",
                f"未来泄漏 {metrics.get('future_leakage_count', '?')}，过期因子 "
                f"{int(metrics.get('fundamental_stale_count') or 0) + int(metrics.get('capital_flow_stale_count') or 0)}",
            ],
        ),
        agent(
            "SCAN",
            "多因子评分",
            "ok" if counts["score_gate"] else "idle",
            f"{counts['score_gate']}/{counts['data_gate']}",
            counts["score_gate"] / max(1, counts["data_gate"]),
            [
                f"{counts['data_gate']} 只完成评分，{counts['score_gate']} 只 ≥ {float(policy.get('buy_threshold', 70)):g} 分",
                f"最高分 {top['symbol']} {float(top['total']):g}（置信 {float(top['confidence']):.2f}）"
                if top
                else "无评分结果",
            ],
        ),
        agent(
            "VET",
            "风险规则否决",
            "alert" if warnings else "ok",
            f"{warnings} 警告",
            1.0 - warnings / max(1, counts["data_gate"]),
            [
                f"风险规则 {warnings} 条警告" + (f"：{rule_text}" if rule_text else ""),
                f"{counts['confidence_gate']} 只候选中 {counts['confidence_gate'] - counts['risk_veto']} 只被否决",
            ],
        ),
        agent(
            "SIZE",
            "仓位分配",
            "ok" if targets else "idle",
            f"{gross:.0%}",
            gross,
            [
                f"{len(targets)} 个目标，总敞口 {gross:.0%}，单票上限 {float(policy.get('maximum_position_weight', 0.08)):.0%}",
                f"回撤乘数 {float(drawdown['exposure_multiplier']):.2f}",
            ],
        ),
        agent(
            "FILLS",
            "模拟执行 · A股约束",
            "alert" if blocked else ("ok" if trades else "idle"),
            f"{len(trades)}/{len(blocked)}",
            len(trades) / max(1, len(trades) + len(blocked)),
            [
                f"今日成交 {len(trades)} 笔，阻断 {len(blocked)} 笔（T+1 / 涨跌停 / 停牌 / 整手）",
                f"{as_of} 收盘信号排队至下一交易日开盘执行" if targets else "无排队目标",
            ],
        ),
        agent(
            "RISK",
            "组合回撤控制",
            "ok" if dd_regime == "normal" else "alert",
            f"DD {float(drawdown['current']):.2%}",
            1.0 - float(drawdown["current"]) / max(1e-9, float(drawdown["limit"])),
            [
                f"回撤状态 {dd_regime}：当前 {float(drawdown['current']):.2%} / 减仓 {float(drawdown['reduce']):.0%}"
                f" / 清仓 {float(drawdown['liquidate']):.0%} / 上限 {float(drawdown['limit']):.0%}",
            ],
        ),
        agent(
            "AUDIT",
            "确定性审计",
            {"ELIGIBLE_FOR_REVIEW": "ok", "FAILED": "alert"}.get(str(header["status"]), "idle"),
            f"{header['valid_sessions']}/{REQUIRED_SESSIONS}",
            int(header["valid_sessions"]) / REQUIRED_SESSIONS,
            [f"审计 {header['status']}：有效交易日 {header['valid_sessions']}/{REQUIRED_SESSIONS}"]
            + [f"失败项：{failure}" for failure in failures[:2]],
        ),
        agent(
            "CHIEF",
            "主管 · 从不持仓",
            "ok",
            "PAPER",
            1.0,
            [
                f"今日决策：{len(targets)} 只目标"
                + ("待 D+1 开盘建仓" if targets else "，保持现金"),
                f"DQN 敞口 {'开启' if policy.get('dqn_exposure_enabled') else '关闭'}，"
                f"实盘 {'开启' if policy.get('live_trading_enabled') else '关闭'}，commit {str(manifest.get('git_sha', ''))[:7]}",
            ],
        ),
    ]


def _quote(quote_map: Mapping[str, Mapping[str, object]], symbol: str) -> dict[str, object] | None:
    row = quote_map.get(symbol)
    if row is None:
        return None
    return {"price": float(row["price"]), "change_pct": _float_or_none(row.get("change_pct"))}


def _load_targets(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [
            {
                "symbol": row["symbol"],
                "target_weight": float(row["target_weight"]),
                "raw_target_weight": float(row["raw_target_weight"]),
                "score": float(row["score"]),
                "score_confidence": float(row["score_confidence"]),
                "reason": row["reason"],
            }
            for row in csv.DictReader(handle)
        ]


def _load_benchmark(path: Path) -> list[tuple[str, float]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [(row["trade_date"], float(row["index_close"])) for row in csv.DictReader(handle)]


def _load_names(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["symbol"]: row.get("name", "") for row in csv.DictReader(handle)}


def load_quotes_csv(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [row for row in csv.DictReader(handle) if row.get("price")]


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _is_date(text: str) -> bool:
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True
