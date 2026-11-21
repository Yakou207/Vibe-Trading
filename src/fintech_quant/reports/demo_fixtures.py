"""Self-contained synthetic demo workspace for ``serve_trading_desk.py --demo`` and GitHub Pages.

Everything generated here is clearly labelled synthetic sample data so visitors can launch the
pixel-office trading desk, stock picker, shadow pools, event NLP and Jev advisory panels with
zero third-party dependencies, zero network calls and zero API keys. It never reads or mutates
canonical ``data/`` or ``outputs/`` directories.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Mapping

from fintech_quant.data.run_artifacts import sha256_file
from fintech_quant.information.event_nlp import analyze_items, financial_trend, research_consensus
from fintech_quant.reports.picker import PickerData, resolve_symbol
from fintech_quant.research import momentum_pool, momentum_pool_v2
from fintech_quant.research.momentum_setup import Bar, SymbolSeries, screen


DEMO_AS_OF = "2026-11-05"
DEMO_SESSIONS = 200
DEMO_CYCLE_COUNT = 5

DEMO_STOCKS: tuple[dict[str, object], ...] = (
    {
        "symbol": "300750.SZ",
        "name": "宁德时代",
        "industry": "电力设备",
        "profile": "trigger",
        "base_price": 185.0,
        "ratio": 0.92,
        "score": 81.4,
        "confidence": 0.92,
        "v2_score": 91.2,
        "roe": 21.8,
        "rev_yoy": 14.6,
        "profit_yoy": 22.4,
    },
    {
        "symbol": "601899.SH",
        "name": "紫金矿业",
        "industry": "有色金属",
        "profile": "trigger",
        "base_price": 14.2,
        "ratio": 0.88,
        "score": 77.8,
        "confidence": 0.88,
        "v2_score": 86.5,
        "roe": 23.1,
        "rev_yoy": 11.2,
        "profit_yoy": 31.5,
    },
    {
        "symbol": "002594.SZ",
        "name": "比亚迪",
        "industry": "汽车",
        "profile": "setup",
        "base_price": 248.0,
        "ratio": 0.95,
        "score": 75.2,
        "confidence": 0.85,
        "v2_score": 82.0,
        "roe": 20.4,
        "rev_yoy": 18.9,
        "profit_yoy": 19.7,
    },
    {
        "symbol": "000333.SZ",
        "name": "美的集团",
        "industry": "家用电器",
        "profile": "setup",
        "base_price": 62.5,
        "ratio": 0.84,
        "score": 73.6,
        "confidence": 0.84,
        "v2_score": 79.4,
        "roe": 22.6,
        "rev_yoy": 9.8,
        "profit_yoy": 13.4,
    },
    {
        "symbol": "600900.SH",
        "name": "长江电力",
        "industry": "公用事业",
        "profile": "leader_no_base",
        "base_price": 26.8,
        "ratio": 0.91,
        "score": 71.5,
        "confidence": 0.86,
        "v2_score": 74.1,
        "roe": 15.2,
        "rev_yoy": 6.4,
        "profit_yoy": 8.9,
    },
    {
        "symbol": "600036.SH",
        "name": "招商银行",
        "industry": "银行",
        "profile": "vetoed",
        "base_price": 34.5,
        "ratio": 0.82,
        "score": 72.4,
        "confidence": 0.83,
        "v2_score": 68.3,
        "roe": 15.8,
        "rev_yoy": 2.1,
        "profit_yoy": 3.8,
    },
    {
        "symbol": "601318.SH",
        "name": "中国平安",
        "industry": "非银金融",
        "profile": "sideways",
        "base_price": 48.0,
        "ratio": 0.86,
        "score": 64.8,
        "confidence": 0.81,
        "v2_score": 58.7,
        "roe": 13.4,
        "rev_yoy": 4.5,
        "profit_yoy": 6.2,
    },
    {
        "symbol": "600519.SH",
        "name": "贵州茅台",
        "industry": "食品饮料",
        "profile": "sideways",
        "base_price": 1520.0,
        "ratio": 0.78,
        "score": 62.1,
        "confidence": 0.90,
        "v2_score": 55.2,
        "roe": 34.5,
        "rev_yoy": 8.2,
        "profit_yoy": 9.1,
    },
    {
        "symbol": "600276.SH",
        "name": "恒瑞医药",
        "industry": "医药生物",
        "profile": "downtrend",
        "base_price": 46.5,
        "ratio": 0.90,
        "score": 54.3,
        "confidence": 0.78,
        "v2_score": 41.8,
        "roe": 12.1,
        "rev_yoy": 5.3,
        "profit_yoy": 4.0,
    },
    {
        "symbol": "000858.SZ",
        "name": "五粮液",
        "industry": "食品饮料",
        "profile": "downtrend",
        "base_price": 138.0,
        "ratio": 0.83,
        "score": 49.6,
        "confidence": 0.76,
        "v2_score": 33.4,
        "roe": 21.0,
        "rev_yoy": -1.8,
        "profit_yoy": -3.2,
    },
)


@dataclass(frozen=True)
class DemoPaths:
    root: Path
    cycle_root: Path
    pnl_curve: Path
    state: Path
    pool_root: Path
    pool_v2_root: Path
    intraday_root: Path
    scoring_v2: Path
    intel_cache: Path
    jev_records: Path


def _trading_days(count: int, end_iso: str = DEMO_AS_OF) -> list[str]:
    end = date.fromisoformat(end_iso)
    days: list[str] = []
    cur = end
    while len(days) < count:
        if cur.weekday() < 5:
            days.append(cur.isoformat())
        cur -= timedelta(days=1)
    days.reverse()
    return days


def _make_series(spec: Mapping[str, object], days: list[str]) -> SymbolSeries:
    symbol = str(spec["symbol"])
    profile = str(spec["profile"])
    base = float(spec["base_price"])
    n = len(days)

    if profile == "trigger":
        scale = base / 10.0
        closes = [(10.0 + 0.07 * i) * scale for i in range(n - 60)]
        closes += [(19.6 + 0.4 * ((i % 6) / 5.0) + 0.012 * i) * scale for i in range(59)]
        bars = [
            Bar(d, c, c * 1.01, c * 0.99, c, 1_800_000.0)
            for d, c in zip(days[:-1], closes)
        ]
        draft = SymbolSeries(symbol, bars + [bars[-1]])
        zone_low = min(draft.ema9[-2], draft.ema21[-2])
        zone_high = max(draft.ema9[-2], draft.ema21[-2])
        last_close = max(zone_high * 1.005, bars[-1].close * 1.003)
        bars.append(
            Bar(
                days[-1],
                round(zone_high * 1.001, 4),
                round(last_close * 1.003, 4),
                round(zone_low * 0.998, 4),
                round(last_close, 4),
                3_200_000.0,
            )
        )
        return SymbolSeries(symbol, bars)

    if profile == "setup":
        scale = base / 10.0
        closes = [(10.0 + 0.062 * i) * scale for i in range(n - 55)]
        closes += [(18.7 + 0.35 * ((i % 7) / 6.0) + 0.008 * i) * scale for i in range(55)]
        bars = [
            Bar(d, c * 0.998, c * 1.012, c * 0.988, c, 1_400_000.0)
            for d, c in zip(days, closes)
        ]
        return SymbolSeries(symbol, bars)

    if profile == "leader_no_base":
        closes = [base * (1.0 + 0.0022 * i + 0.008 * math.sin(i / 4.0)) for i in range(n)]
        bars = [
            Bar(d, c * 0.996, c * 1.014, c * 0.989, c, 1_100_000.0)
            for d, c in zip(days, closes)
        ]
        return SymbolSeries(symbol, bars)

    if profile == "vetoed":
        closes = [base * (1.0 + 0.0009 * i + 0.015 * math.sin(i / 7.0)) for i in range(n)]
        bars = [
            Bar(d, c * 1.002, c * 1.013, c * 0.986, c, 950_000.0)
            for d, c in zip(days, closes)
        ]
        return SymbolSeries(symbol, bars)

    if profile == "sideways":
        closes = [base * (1.0 + 0.025 * math.sin(i / 11.0)) for i in range(n)]
        bars = [
            Bar(d, c * 0.999, c * 1.011, c * 0.989, c, 850_000.0)
            for d, c in zip(days, closes)
        ]
        return SymbolSeries(symbol, bars)

    # downtrend
    closes = [base * (1.0 - 0.0012 * i + 0.012 * math.sin(i / 6.0)) for i in range(n)]
    bars = [
        Bar(d, c * 1.003, c * 1.01, c * 0.985, c, 780_000.0)
        for d, c in zip(days, closes)
    ]
    return SymbolSeries(symbol, bars)


def _file_ref(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    return {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_processed_manifest(run_dir: Path, artifact_name: str) -> Path:
    artifact = run_dir / artifact_name
    manifest = run_dir / "processed_manifest.json"
    _write_json(
        manifest,
        {
            "layer": "processed",
            "mode": "synthetic_demo",
            "as_of": DEMO_AS_OF,
            "artifacts": [
                {
                    "path": artifact_name,
                    "bytes": artifact.stat().st_size,
                    "sha256": sha256_file(artifact),
                }
            ],
        },
    )
    return manifest


def _score_row(spec: Mapping[str, object], day_offset: int) -> dict[str, object]:
    total = round(float(spec["score"]) + day_offset * 0.25, 2)
    conf = float(spec["confidence"])
    fund = round(min(35.0, total * 0.41), 2)
    tech = round(min(25.0, total * 0.27), 2)
    flow = round(min(25.0, total * 0.21), 2)
    sent = round(max(0.0, total - fund - tech - flow), 2)
    return {
        "symbol": str(spec["symbol"]),
        "total": total,
        "confidence": conf,
        "components": {
            "fundamental": {
                "score": fund,
                "max_score": 35.0,
                "reasons": [
                    f"ROE {spec['roe']}% / Revenue YoY {spec['rev_yoy']}% (synthetic demo sample)"
                ],
            },
            "technical": {
                "score": tech,
                "max_score": 25.0,
                "reasons": ["Trend alignment and volatility compression check"],
            },
            "capital_flow": {
                "score": flow,
                "max_score": 25.0,
                "reasons": ["Turnover and liquidity stability proxy"],
            },
            "sentiment": {
                "score": sent,
                "max_score": 15.0,
                "reasons": ["Demo event NLP net score"],
            },
        },
    }


def build_demo_workspace(root: Path) -> DemoPaths:
    """Materialize a complete, hash-verified synthetic demo workspace under ``root``."""
    root = root.resolve()
    days = _trading_days(DEMO_SESSIONS, DEMO_AS_OF)
    cycle_days = days[-DEMO_CYCLE_COUNT:]
    series = {str(spec["symbol"]): _make_series(spec, days) for spec in DEMO_STOCKS}

    # 1. Processed signal (hfq) and execution (unadjusted) price snapshots
    signal_dir = root / "processed" / "signal_price"
    exec_dir = root / "processed" / "execution_price"
    signal_dir.mkdir(parents=True, exist_ok=True)
    exec_dir.mkdir(parents=True, exist_ok=True)

    features_csv = signal_dir / "features.csv"
    with features_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["trade_date", "symbol", "open", "high", "low", "close", "volume", "is_suspended"]
        )
        for spec in DEMO_STOCKS:
            sym = str(spec["symbol"])
            for bar in series[sym].bars:
                writer.writerow(
                    [
                        bar.trade_date,
                        sym,
                        f"{bar.open:.4f}",
                        f"{bar.high:.4f}",
                        f"{bar.low:.4f}",
                        f"{bar.close:.4f}",
                        f"{bar.volume:.0f}",
                        "false",
                    ]
                )
    signal_manifest = _write_processed_manifest(signal_dir, "features.csv")

    daily_csv = exec_dir / "daily.csv"
    with daily_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["trade_date", "symbol", "close"])
        for spec in DEMO_STOCKS:
            sym = str(spec["symbol"])
            ratio = float(spec["ratio"])
            for bar in series[sym].bars[-15:]:
                writer.writerow([bar.trade_date, sym, f"{bar.close * ratio:.4f}"])
    exec_manifest = _write_processed_manifest(exec_dir, "daily.csv")

    # 2. Membership and universe
    membership_csv = root / "membership.csv"
    with membership_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["index_code", "symbol", "member_from", "member_to", "source", "source_fetched_at"]
        )
        for spec in DEMO_STOCKS:
            writer.writerow(
                [
                    "000300",
                    str(spec["symbol"]),
                    days[0],
                    "",
                    "synthetic_demo",
                    f"{DEMO_AS_OF}T09:00:00Z",
                ]
            )

    universe_csv = root / "current_universe.csv"
    with universe_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol", "name"])
        for spec in DEMO_STOCKS:
            writer.writerow([str(spec["symbol"]), str(spec["name"])])

    # 3. Hash-linked post-close paper cycles (5 sessions)
    cycle_root = root / "cycles"
    policy = {
        "buy_threshold": 70.0,
        "minimum_score_confidence": 0.8,
        "maximum_position_weight": 0.08,
        "drawdown_reduce": 0.08,
        "drawdown_liquidate": 0.09,
        "drawdown_validation_limit": 0.1,
        "dqn_exposure_enabled": False,
        "live_trading_enabled": False,
        "strategy": "scored_multi_factor_baseline (DEMO)",
    }

    equity_path = [100000.0, 100420.0, 100180.0, 100890.0, 101340.0]
    bench_path = [3920.0, 3934.0, 3918.0, 3946.0, 3962.0]
    parent_sha: str | None = None
    latest_decision_path = cycle_root / DEMO_AS_OF / "decision_report.json"

    for idx, day in enumerate(cycle_days):
        cdir = cycle_root / day
        cdir.mkdir(parents=True, exist_ok=True)
        scores = [_score_row(spec, idx - (DEMO_CYCLE_COUNT - 1)) for spec in DEMO_STOCKS]
        decision_payload = {
            "as_of": day,
            "active_member_count": len(DEMO_STOCKS),
            "data_health_passed": True,
            "data_health": {
                "passed": True,
                "metrics": {
                    "price_coverage": 1.0,
                    "fundamental_coverage": 1.0,
                    "demo_mode": True,
                },
            },
            "scores": scores,
            "risk_limits": {"max_position_weight": 0.08},
            "risk_summary": {"total_warnings": 1, "by_rule": {"main_outflow": 1}},
            "risk_warnings": [
                {
                    "symbol": "600036.SH",
                    "rule": "main_outflow",
                    "action": "reduce",
                    "message": "Demo risk rule: capital-flow proxy triggered position cap.",
                }
            ],
        }
        _write_json(cdir / "decision_report.json", decision_payload)

        nav_history = [
            {"trade_date": cycle_days[i], "equity": equity_path[i]} for i in range(idx + 1)
        ]
        cur_equity = equity_path[idx]
        paper_return = round((cur_equity / equity_path[0]) - 1.0, 4)
        bench_return = round((bench_path[idx] / bench_path[0]) - 1.0, 4)
        excess = round(paper_return - bench_return, 4)

        _write_json(
            cdir / "paper_report.json",
            {
                "account": {
                    "cash": round(cur_equity - 15740.0, 2),
                    "positions": {
                        "300750.SZ": {
                            "shares": 100,
                            "cost_basis": 152.8,
                            "last_buy_date": cycle_days[0],
                        },
                        "601899.SH": {
                            "shares": 200,
                            "cost_basis": 12.1,
                            "last_buy_date": cycle_days[min(1, idx)],
                        },
                    },
                    "drawdown_control_state": {
                        "actual_peak": max(equity_path[: idx + 1]),
                        "regime": "normal",
                        "transitions": [],
                    },
                    "pending_signal_date": day,
                    "nav_history": nav_history,
                    "shadow_nav_history": nav_history,
                },
                "nav": {"equity": cur_equity, "exposure_multiplier": 1.0},
                "trades": [
                    {
                        "trade_date": cycle_days[0],
                        "symbol": "300750.SZ",
                        "side": "buy",
                        "shares": 100,
                        "price": 152.8,
                        "commission": 5.0,
                        "stamp_duty": 0.0,
                    }
                ],
                "blocked_orders": [],
            },
        )
        _write_json(
            cdir / "validation_report.json",
            {
                "status": "DEMO_PENDING_WINDOW",
                "live_trading_authorized": False,
                "failures": [
                    f"Synthetic demo window ({idx + 1}/40 sessions) — paper evidence only"
                ],
                "gates": {
                    "hash_chain_integrity": {"observed": True, "passed": True, "required": True},
                    "account_continuity": {"observed": True, "passed": True, "required": True},
                    "drawdown_limit": {"observed": 0.0024, "passed": True, "required": 0.1},
                    "minimum_sessions": {
                        "observed": idx + 1,
                        "passed": False,
                        "required": 40,
                    },
                },
                "metrics": {
                    "valid_sessions": idx + 1,
                    "paper_return": paper_return,
                    "benchmark_return": bench_return,
                    "excess_return": excess,
                },
                "window": {"anchor_date": cycle_days[0], "calendar_days": idx + 1},
            },
        )
        (cdir / "csi300_market_state.csv").write_text(
            "trade_date,index_symbol,index_close\n"
            + "".join(
                f"{cycle_days[i]},sh000300,{bench_path[i]}\n" for i in range(idx + 1)
            ),
            encoding="utf-8",
        )
        (cdir / "current_universe.csv").write_text(
            universe_csv.read_text(encoding="utf-8"), encoding="utf-8"
        )
        (cdir / "targets.csv").write_text(
            "symbol,raw_target_weight,target_weight,portfolio_exposure_multiplier,"
            "score,score_confidence,rl_action,reason\n"
            "300750.SZ,0.08,0.08,1.0,81.4,0.92,buy,score=81.40 (demo)\n"
            "601899.SH,0.08,0.08,1.0,77.8,0.88,buy,score=77.80 (demo)\n"
            "002594.SZ,0.08,0.08,1.0,75.2,0.85,buy,score=75.20 (demo)\n",
            encoding="utf-8",
        )
        manifest_path = cdir / "cycle_manifest.json"
        _write_json(
            manifest_path,
            {
                "schema_version": 2,
                "as_of": day,
                "git_sha": "demo-snapshot",
                "policy": policy,
                "evidence_parent": {"sha256": parent_sha} if parent_sha else None,
            },
        )
        parent_sha = sha256_file(manifest_path)

    # 4. Pipeline state (hash-bound for load_picker_data)
    state_path = root / "pipeline_state.json"
    _write_json(
        state_path,
        {
            "last_successful_as_of": DEMO_AS_OF,
            "manifests": {
                "signal_price": {"processed_manifest": str(signal_manifest.resolve())},
                "execution_price": {"processed_manifest": str(exec_manifest.resolve())},
            },
            "decision_report": _file_ref(latest_decision_path),
            "current_universe": _file_ref(universe_csv),
            "membership": _file_ref(membership_csv),
        },
    )

    # 5. Backtest PnL curve (illustrative curve reflecting the withdrawn-leak honest rerun)
    pnl_curve_path = root / "pnl_curve.json"
    curve_dates = days[::10]
    if curve_dates[-1] != DEMO_AS_OF:
        curve_dates.append(DEMO_AS_OF)
    m = len(curve_dates)
    _write_json(
        pnl_curve_path,
        {
            "dates": curve_dates,
            "series": {
                "baseline": {
                    "label": "Risk-controlled baseline (−17.0% honest rerun)",
                    "equity": [
                        round(100000.0 * (1.0 - 0.17 * (i / max(1, m - 1))), 2) for i in range(m)
                    ],
                },
                "csi300_tr": {
                    "label": "CSI 300 Total Return (+3.7%)",
                    "equity": [
                        round(
                            100000.0
                            * (1.0 + 0.037 * (i / max(1, m - 1)) + 0.025 * math.sin(i / 2.2)),
                            2,
                        )
                        for i in range(m)
                    ],
                },
            },
        },
    )

    # 6. Shadow pools (v1 & v2) stepped deterministically from the real pool logic
    members = set(series)
    screen_results = screen(series, DEMO_AS_OF, members=members)
    pool_state = momentum_pool.step_pool(
        momentum_pool.initial_pool_state(),
        as_of=DEMO_AS_OF,
        series=series,
        screen_results=screen_results,
        previous_session=cycle_days[-2],
    )
    pool_root = root / "momentum_pool"
    _write_json(pool_root / "state.json", pool_state)

    pool_v2_state = momentum_pool_v2.step_pool(
        momentum_pool_v2.initial_pool_state(),
        as_of=DEMO_AS_OF,
        series=series,
        screen_results=screen_results,
        previous_session=cycle_days[-2],
    )
    pool_v2_root = root / "momentum_pool_v2"
    _write_json(pool_v2_root / "state.json", pool_v2_state)

    # 7. Scoring v2 research snapshot
    scoring_v2_path = root / "scoring_v2" / "latest_scores.json"
    _write_json(
        scoring_v2_path,
        {
            "as_of": DEMO_AS_OF,
            "label": "研究评分 v2（横截面排名合成 · Demo 样例），不驱动计数策略",
            "signs": {"ep": 1, "roe": 1, "mom_12_1": 1, "vol_60d": -1},
            "scores": {
                str(spec["symbol"]): {
                    "score": float(spec["v2_score"]),
                    "coverage": 0.9259,
                    "categories": {
                        "value": {
                            "z": round((float(spec["v2_score"]) - 60.0) / 25.0, 2),
                            "percentile": float(spec["v2_score"]),
                            "weight": 0.25,
                        },
                        "quality": {
                            "z": round((float(spec["roe"]) - 16.0) / 8.0, 2),
                            "percentile": min(99.0, round(float(spec["roe"]) * 3.8, 1)),
                            "weight": 0.25,
                        },
                        "momentum": {
                            "z": round((float(spec["v2_score"]) - 55.0) / 22.0, 2),
                            "percentile": float(spec["v2_score"]),
                            "weight": 0.30,
                        },
                        "low_vol": {
                            "z": 0.45,
                            "percentile": 66.0,
                            "weight": 0.20,
                        },
                    },
                }
                for spec in DEMO_STOCKS
            },
        },
    )

    intel_cache = root / "research_cache"
    jev_records = root / "jev"
    intraday_root = root / "momentum_pool_intraday"
    intel_cache.mkdir(parents=True, exist_ok=True)
    jev_records.mkdir(parents=True, exist_ok=True)
    intraday_root.mkdir(parents=True, exist_ok=True)

    return DemoPaths(
        root=root,
        cycle_root=cycle_root,
        pnl_curve=pnl_curve_path,
        state=state_path,
        pool_root=pool_root,
        pool_v2_root=pool_v2_root,
        intraday_root=intraday_root,
        scoring_v2=scoring_v2_path,
        intel_cache=intel_cache,
        jev_records=jev_records,
    )


def _stock_spec(symbol: str) -> dict[str, object]:
    for spec in DEMO_STOCKS:
        if spec["symbol"] == symbol:
            return dict(spec)
    return dict(DEMO_STOCKS[0])


def demo_research_payload(data: PickerData, query: str) -> dict[str, object]:
    """Offline synthetic Event NLP + financial trend + cached Jev status for demo mode."""
    symbol = resolve_symbol(data, query)
    if symbol is None:
        return {"error": f"Demo 模式仅包含 10 只沪深 300 样例股，未找到：{query}"}
    spec = _stock_spec(symbol)
    name = str(spec["name"])
    day = date.fromisoformat(DEMO_AS_OF)

    raw_items = [
        {
            "source": "cninfo_notice",
            "title": f"[DEMO] {name}发布三季报：营收同比增长 {spec['rev_yoy']}%，归母净利润同比变动 {spec['profit_yoy']}%",
            "published_at": f"{DEMO_AS_OF} 08:15",
            "url": "",
            "summary": "合成演示公告：用于展示规则型事件 NLP 与财报趋势面板，非真实实时公告。",
        },
        {
            "source": "research_report",
            "title": f"[DEMO] 券商点评：{name}盈利能力稳健，维持“买入”评级",
            "published_at": "2026-11-03 10:30",
            "rating": "买入",
            "url": "",
            "summary": "合成演示研报摘要。",
        },
        {
            "source": "eastmoney_news",
            "title": f"[DEMO] {spec['industry']}板块景气度跟踪：{name}产能利用率维持高位",
            "published_at": "2026-11-01 14:20",
            "url": "",
            "summary": "合成演示资讯。",
        },
    ]
    nlp = analyze_items(raw_items, today=day, name=name, symbol=symbol)
    financials = [
        {
            "period": "2026Q3",
            "roe": float(spec["roe"]),
            "revenue_yoy": float(spec["rev_yoy"]),
            "net_profit_yoy": float(spec["profit_yoy"]),
        },
        {
            "period": "2026Q2",
            "roe": round(float(spec["roe"]) - 0.8, 1),
            "revenue_yoy": round(float(spec["rev_yoy"]) - 1.1, 1),
            "net_profit_yoy": round(float(spec["profit_yoy"]) - 1.4, 1),
        },
        {
            "period": "2026Q1",
            "roe": round(float(spec["roe"]) - 1.5, 1),
            "revenue_yoy": round(float(spec["rev_yoy"]) - 2.0, 1),
            "net_profit_yoy": round(float(spec["profit_yoy"]) - 2.5, 1),
        },
    ]
    jev_record = demo_jev_payload(data, symbol)
    return {
        "symbol": symbol,
        "name": name,
        "fetched_at": f"{DEMO_AS_OF}T16:35:00Z (demo)",
        "sources": {
            "cninfo_notice": {"ok": True, "count": 1},
            "research_report": {"ok": True, "count": 1},
            "eastmoney_news": {"ok": True, "count": 1},
        },
        "global": {
            "industry": str(spec["industry"]),
            "industry_keywords": [str(spec["industry"]), "CSI 300 Demo"],
            "overseas": [],
        },
        "nlp": {k: v for k, v in nlp.items() if k != "items"},
        "items": nlp["items"],
        "consensus": research_consensus(raw_items, today=day),
        "financials": financials,
        "financial_trend": financial_trend(financials),
        "comment_scores": [],
        "jev": {
            "configured": True,
            "provider": "demo",
            "model": "Jev-Demo (offline)",
            "reason": "Offline synthetic demo verdict",
        },
        "events_llm": {"configured": False, "model": "", "reason": "Disabled in offline demo mode"},
        "jev_packet_sha256": hashlib.sha256(f"demo-{symbol}-{DEMO_AS_OF}".encode()).hexdigest(),
        "jev_record": jev_record,
        "jev_spend": {"today_usd": 0.0, "total_usd": 0.0, "calls_today": 0},
    }


def demo_jev_payload(data: PickerData, query: str) -> dict[str, object]:
    """Deterministic offline TypeSafe Jev advisory verdict for demo mode."""
    symbol = resolve_symbol(data, query)
    if symbol is None:
        return {"error": f"Demo 模式未找到：{query}"}
    spec = _stock_spec(symbol)
    profile = str(spec["profile"])

    if profile == "trigger":
        verdict, label = "support", "支持观察/入场（Demo 建议性裁决）"
        probs = [0.78, 0.74, 0.14, 0.18, 0.76]
    elif profile == "setup":
        verdict, label = "neutral", "中性等待确认（Demo 建议性裁决）"
        probs = [0.64, 0.62, 0.22, 0.26, 0.60]
    else:
        verdict, label = "veto", "否决 / 回避（Demo 建议性裁决）"
        probs = [0.34, 0.38, 0.62, 0.58, 0.32]

    questions = [
        "趋势与平台结构是否支撑多头延续？",
        "最新财报与事件面是否无明显恶化？",
        "是否存在未消化重大监管/减持/诉讼风险？",
        "短期波动或换手是否显示筹码松动？",
        "风险收益比是否满足严格止损纪律？",
    ]
    return {
        "symbol": symbol,
        "as_of": DEMO_AS_OF,
        "model": "Jev-Demo (offline)",
        "provider": "demo",
        "cached": True,
        "advisory_only": True,
        "verdict": verdict,
        "verdict_label": label,
        "summary": (
            f"[DEMO] {spec['name']} ({symbol}) 的离线示例裁决：仅用于演示 Jev 概率阈值交互，"
            "不接入实盘且不修改计数策略。"
        ),
        "answers": [
            {"question": q, "probability": p, "rationale": "Synthetic offline demo score"}
            for q, p in zip(questions, probs)
        ],
        "cost_usd": 0.0,
    }
