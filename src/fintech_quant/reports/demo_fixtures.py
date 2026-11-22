"""Self-contained fictional demo workspace for ``serve_trading_desk.py --demo`` and GitHub Pages.

Everything generated here uses strictly fictional tickers (``999001.SH``..``999010.SH``, a
reserved numeric range with no listed A-share companies) and synthetic sample data so visitors
can inspect the pixel-office trading desk, stock picker, shadow pools, event NLP and Jev
advisory workflow with only numpy and pandas installed, zero network calls and zero API keys. It
never reads or mutates canonical ``data/`` or ``outputs/`` directories, and never references
real listed companies.
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
        "symbol": "999001.SH",
        "name": "曜辰新能",
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
        "symbol": "999002.SH",
        "name": "远岳矿业",
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
        "symbol": "999003.SH",
        "name": "明川汽车",
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
        "symbol": "999004.SH",
        "name": "澄明智家",
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
        "symbol": "999005.SH",
        "name": "清岚电力",
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
        "symbol": "999006.SH",
        "name": "东衡银行",
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
        "symbol": "999007.SH",
        "name": "安澜人寿",
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
        "symbol": "999008.SH",
        "name": "云禾食品",
        "industry": "食品饮料",
        "profile": "sideways",
        "base_price": 152.0,
        "ratio": 0.78,
        "score": 62.1,
        "confidence": 0.90,
        "v2_score": 55.2,
        "roe": 24.5,
        "rev_yoy": 8.2,
        "profit_yoy": 9.1,
    },
    {
        "symbol": "999009.SH",
        "name": "青梧生物",
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
        "symbol": "999010.SH",
        "name": "铸衡精工",
        "industry": "机械设备",
        "profile": "downtrend",
        "base_price": 38.0,
        "ratio": 0.83,
        "score": 49.6,
        "confidence": 0.76,
        "v2_score": 33.4,
        "roe": 11.0,
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
            "mode": "demo",
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
                "reasons": [f"ROE {spec['roe']}% / 营收同比 {spec['rev_yoy']}%"],
            },
            "technical": {
                "score": tech,
                "max_score": 25.0,
                "reasons": ["趋势排列与波动收敛检验"],
            },
            "capital_flow": {
                "score": flow,
                "max_score": 25.0,
                "reasons": ["换手与流动性稳定性代理指标"],
            },
            "sentiment": {
                "score": sent,
                "max_score": 15.0,
                "reasons": ["事件 NLP 净情感分"],
            },
        },
    }


def build_demo_workspace(root: Path) -> DemoPaths:
    """Materialize a complete, hash-verified fictional demo workspace under ``root``."""
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
                    "DEMO300",
                    str(spec["symbol"]),
                    days[0],
                    "",
                    "demo",
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
        "commission_rate": 0.0003,
        "minimum_commission": 5.0,
        "slippage_rate": 0.0005,
        "drawdown_reduce": 0.08,
        "drawdown_liquidate": 0.09,
        "drawdown_validation_limit": 0.1,
        "dqn_exposure_enabled": False,
        "live_trading_enabled": False,
        "strategy": "scored_multi_factor_baseline",
    }

    bench_path = [3920.0, 3934.0, 3918.0, 3946.0, 3962.0]
    equity_path = [round(100000.0 * b / bench_path[0], 2) for b in bench_path]
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
                    "symbol": "999006.SH",
                    "rule": "main_outflow",
                    "action": "reduce",
                    "message": "资金流代理指标触发仓位上限规则。",
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

        _write_json(
            cdir / "paper_report.json",
            {
                "account": {
                    "cash": round(cur_equity - 21950.0, 2),
                    "positions": {
                        "999001.SH": {
                            "shares": 100,
                            "cost_basis": 152.8,
                            "last_buy_date": cycle_days[0],
                        },
                        "999002.SH": {
                            "shares": 200,
                            "cost_basis": 12.1,
                            "last_buy_date": cycle_days[min(1, idx)],
                        },
                        "999009.SH": {
                            "shares": 100,
                            "cost_basis": 42.5,
                            "last_buy_date": cycle_days[0],
                        },
                    },
                    "drawdown_control_state": {
                        "actual_peak": max(equity_path[: idx + 1]),
                        "regime": "normal",
                        "transitions": [],
                    },
                    "pending_signal_date": day,
                    "pending_targets": {
                        "999001.SH": 0.08,
                        "999002.SH": 0.08,
                        "999003.SH": 0.08,
                    },
                    "nav_history": nav_history,
                    "shadow_nav_history": nav_history,
                },
                "nav": {"equity": cur_equity, "exposure_multiplier": 1.0},
                "trades": [
                    {
                        "trade_date": cycle_days[0],
                        "symbol": "999001.SH",
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
                "failures": [f"验证窗口未满（{idx + 1}/40 个交易日，离线演示）"],
                "gates": {
                    "hash_chain_integrity": {"observed": True, "passed": True, "required": True},
                    "account_continuity": {"observed": True, "passed": True, "required": True},
                    "drawdown_limit": {"observed": 0.0041, "passed": True, "required": 0.1},
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
                    "excess_return": None,
                },
                "window": {"anchor_date": cycle_days[0], "calendar_days": idx + 1},
            },
        )
        (cdir / "csi300_market_state.csv").write_text(
            "trade_date,index_symbol,index_close\n"
            + "".join(
                f"{cycle_days[i]},demo000300,{bench_path[i]}\n" for i in range(idx + 1)
            ),
            encoding="utf-8",
        )
        (cdir / "current_universe.csv").write_text(
            universe_csv.read_text(encoding="utf-8"), encoding="utf-8"
        )
        (cdir / "targets.csv").write_text(
            "symbol,raw_target_weight,target_weight,portfolio_exposure_multiplier,"
            "score,score_confidence,rl_action,reason\n"
            "999001.SH,0.08,0.08,1.0,81.4,0.92,buy,score=81.40\n"
            "999002.SH,0.08,0.08,1.0,77.8,0.88,buy,score=77.80\n"
            "999003.SH,0.08,0.08,1.0,75.2,0.85,buy,score=75.20\n",
            encoding="utf-8",
        )
        manifest_path = cdir / "cycle_manifest.json"
        _write_json(
            manifest_path,
            {
                "schema_version": 2,
                "kind": "paper_trading_cycle",
                "as_of": day,
                "git_sha": "demo-snapshot",
                "policy": policy,
                "artifacts": {
                    "targets": _file_ref(cdir / "targets.csv"),
                    "paper_report": _file_ref(cdir / "paper_report.json"),
                },
                "inputs": {
                    "execution_prices": _file_ref(daily_csv),
                    "current_universe": _file_ref(cdir / "current_universe.csv"),
                },
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
    risk_controlled_equity = [
        round(100000.0 * (1.0 - 0.17 * (i / max(1, m - 1))), 2) for i in range(m)
    ]
    unrestricted_equity = [
        round(100000.0 * (1.0 - 0.344 * (i / max(1, m - 1))), 2) for i in range(m)
    ]
    csi300_equity = [
        round(
            100000.0
            * (
                1.0
                + 0.037 * (i / max(1, m - 1))
                + 0.025 * math.sin(3.0 * math.pi * i / max(1, m - 1))
            ),
            2,
        )
        for i in range(m)
    ]
    _write_json(
        pnl_curve_path,
        {
            "dates": curve_dates,
            "series": {
                "risk_controlled": {
                    "label": "Risk-controlled baseline（示意，端点 −17.0%）",
                    "equity": risk_controlled_equity,
                },
                "baseline": {
                    "label": "Unrestricted baseline（示意，端点 −34.4%）",
                    "equity": unrestricted_equity,
                },
                "csi300": {
                    "label": "CSI 300 Total Return（示意，端点 +3.7%）",
                    "equity": csi300_equity,
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
            "label": "研究评分 v2（横截面排名），不驱动计数策略",
            "signs": {
                "ep": 1, "bp": 1, "roe": -1, "growth": -1, "vol_60d": -1,
                "max_ret_20d": -1, "turnover_20d": -1, "rev_5d": 1, "mom_12m_skip1m": 1,
            },
            "scores": {
                str(spec["symbol"]): {
                    "score": float(spec["v2_score"]),
                    "coverage": 0.9259,
                    "categories": {
                        key: {
                            "z": round((pct - 50.0) / 30.0, 2),
                            "percentile": pct,
                            "weight": weight,
                        }
                        for key, pct, weight in _v2_categories(spec)
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


# Category keys, training-window weights and demo percentile offsets from the stock's v2 score.
# The keys and weights match the real scoring v2 snapshot; the picker renders exactly these six.
V2_CATEGORIES: tuple[tuple[str, float, float], ...] = (
    ("value", 0.1902, 0.0),
    ("quality_growth", 0.1396, -6.0),
    ("low_risk", 0.2597, -12.0),
    ("liquidity", 0.261, -20.0),
    ("reversal", 0.0109, -30.0),
    ("momentum", 0.1387, 4.0),
)


def _v2_categories(spec: Mapping[str, object]) -> list[tuple[str, float, float]]:
    score = float(spec["v2_score"])
    return [
        (key, max(1.0, min(99.0, round(score + offset, 1))), weight)
        for key, weight, offset in V2_CATEGORIES
    ]


def _stock_spec(symbol: str) -> dict[str, object]:
    for spec in DEMO_STOCKS:
        if spec["symbol"] == symbol:
            return dict(spec)
    return dict(DEMO_STOCKS[0])


def demo_research_payload(data: PickerData, query: str) -> dict[str, object]:
    """Offline Event NLP + financial trend + cached Jev status for demo mode."""
    symbol = resolve_symbol(data, query)
    if symbol is None:
        return {"error": f"Demo 模式仅包含 10 只演示标的（999001–999010），未找到：{query}"}
    spec = _stock_spec(symbol)
    name = str(spec["name"])
    day = date.fromisoformat(DEMO_AS_OF)
    rev_sign = "+" if float(spec["rev_yoy"]) >= 0 else ""
    prof_sign = "+" if float(spec["profit_yoy"]) >= 0 else ""

    raw_items = [
        {
            "source": "cninfo_notice",
            "title": (
                f"{name}发布 2026 年三季报：营收同比 {rev_sign}{spec['rev_yoy']}%，"
                f"归母净利同比 {prof_sign}{spec['profit_yoy']}%"
            ),
            "published_at": f"{DEMO_AS_OF} 08:15",
            "url": "",
            "summary": f"前三季度加权 ROE 为 {spec['roe']}%，经营现金流与费用率保持平稳。",
        },
        {
            "source": "research_report",
            "title": f"{name}季报跟踪：{spec['industry']}景气度分化，关注盈利质量与估值匹配",
            "published_at": "2026-11-03 10:30",
            "url": "",
            "summary": "结合三季报口径更新盈利预测模型，跟踪产能利用率与毛利率边际变化。",
        },
        {
            "source": "eastmoney_news",
            "title": f"{spec['industry']}行业周度观察：头部企业订单与库存周期延续分化",
            "published_at": "2026-11-01 14:20",
            "url": "",
            "summary": f"行业高频跟踪显示供给端出清节奏不一，{name}等标的受关注度较高。",
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
        "fetched_at": f"{DEMO_AS_OF}T16:35:00Z",
        "sources": {
            "cninfo_notice": {"ok": True, "count": 1},
            "research_report": {"ok": True, "count": 1},
            "eastmoney_news": {"ok": True, "count": 1},
        },
        "global": {
            "industry": str(spec["industry"]),
            "industry_keywords": [str(spec["industry"])],
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
            "reason": "离线演示输出",
        },
        "events_llm": {"configured": False, "model": "", "reason": "Disabled in offline demo mode"},
        "jev_packet_sha256": hashlib.sha256(f"demo-{symbol}-{DEMO_AS_OF}".encode()).hexdigest(),
        "jev_record": jev_record,
        "jev_spend": {"today_usd": 0.0, "total_usd": 0.0, "calls_today": 0},
    }


def demo_jev_payload(data: PickerData, query: str) -> dict[str, object]:
    """Deterministic offline TypeSafe Jev workflow output for demo mode."""
    symbol = resolve_symbol(data, query)
    if symbol is None:
        return {"error": f"Demo 模式仅包含 10 只演示标的（999001–999010），未找到：{query}"}
    spec = _stock_spec(symbol)
    profile = str(spec["profile"])

    if profile == "trigger":
        verdict, label = "support", "支持"
        probs = [0.78, 0.74, 0.14, 0.18, 0.76]
        rationales = [
            "20 日均线上方且 EMA9/21 多头排列，平台突破放量",
            "三季报营收与净利维持正增长，公告面无负面催化",
            "近期无监管问询、大额减持或重大诉讼公告",
            "近 20 日换手温和放大，筹码结构相对稳定",
            "支撑位距现价约 5%–6%，盈亏比满足止损纪律",
        ]
    elif profile == "setup":
        verdict, label = "neutral", "中性"
        probs = [0.64, 0.62, 0.22, 0.26, 0.60]
        rationales = [
            "中期趋势偏强但仍处于平台整理末段，尚未放量触发",
            "财报指标稳健，基本面与事件面整体中性偏正面",
            "未发现重大监管、减持或诉讼风险",
            "整理期换手收敛，需观察突破时的量能配合",
            "止损空间可控，等待触发确认后盈亏比更佳",
        ]
    else:
        verdict, label = "veto", "否决"
        probs = [0.34, 0.38, 0.62, 0.58, 0.32]
        rationales = [
            "均线结构偏弱或缺乏有效整理平台，趋势延续性不足",
            "增速放缓或存在风控预警，基本面支撑偏弱",
            "存在资金流或事件面风险提示，建议保持谨慎",
            "波动放大且筹码承接不稳，短线回撤风险较高",
            "有效支撑位较远，当前位置风险收益比不占优",
        ]

    questions = [
        "趋势与平台结构是否支撑多头延续？",
        "最新财报与事件面是否无明显恶化？",
        "是否存在未消化的重大监管、减持或诉讼风险？",
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
        "summary": f"{spec['name']} ({symbol}) 离线演示裁决：{label}，仅作研究辅助参考。",
        "answers": [
            {"question": q, "probability": p, "rationale": r}
            for q, p, r in zip(questions, probs, rationales)
        ],
        "cost_usd": 0.0,
    }


def _spark(end: float, change_pct: float, drift: float, amp: float, phase: float) -> list[float]:
    start = end / (1.0 + drift)
    pts: list[float] = []
    for i in range(19):
        t = i / 19.0
        val = start + (end - start) * t + end * amp * math.sin(t * 2.4 * math.pi + phase)
        pts.append(round(val, 2))
    prev = round(end / (1.0 + change_pct), 2)
    pts[-1] = prev
    pts.append(round(end, 2))
    return pts


def demo_premarket_bundle(
    demo: DemoPaths, picker_data: PickerData | None = None
) -> dict[str, object]:
    """Build a rich, offline pre-market brief + sample auction check for demo mode."""
    from fintech_quant.reports.premarket_brief import build_brief, evaluate_auction

    market_pulse: dict[str, object] = {
        "status": "ok",
        "regime": "risk_on",
        "regime_note": "主要宽基站上 20/50 日均线，两市成交温和放大，风险偏好偏积极",
        "indices": [
            {
                "symbol": "000001.SH",
                "name": "上证指数",
                "close": 3386.42,
                "change_pct": 0.0068,
                "sparkline": _spark(3386.42, 0.0068, 0.024, 0.006, 0.2),
                "above_ma20": True,
                "above_ma50": True,
                "above_ma250": True,
            },
            {
                "symbol": "399001.SZ",
                "name": "深证成指",
                "close": 10842.15,
                "change_pct": 0.0112,
                "sparkline": _spark(10842.15, 0.0112, 0.036, 0.009, 0.7),
                "above_ma20": True,
                "above_ma50": True,
                "above_ma250": True,
            },
            {
                "symbol": "399006.SZ",
                "name": "创业板指",
                "close": 2248.60,
                "change_pct": 0.0165,
                "sparkline": _spark(2248.60, 0.0165, 0.048, 0.012, 1.1),
                "above_ma20": True,
                "above_ma50": True,
                "above_ma250": True,
            },
            {
                "symbol": "000300.SH",
                "name": "沪深300",
                "close": 3962.00,
                "change_pct": 0.0041,
                "sparkline": _spark(3962.00, 0.0041, 0.018, 0.005, 0.4),
                "above_ma20": True,
                "above_ma50": True,
                "above_ma250": True,
            },
            {
                "symbol": "000905.SH",
                "name": "中证500",
                "close": 5918.30,
                "change_pct": 0.0094,
                "sparkline": _spark(5918.30, 0.0094, 0.031, 0.008, 1.5),
                "above_ma20": True,
                "above_ma50": True,
                "above_ma250": False,
            },
            {
                "symbol": "000688.SH",
                "name": "科创50",
                "close": 1012.85,
                "change_pct": -0.0038,
                "sparkline": _spark(1012.85, -0.0038, -0.009, 0.011, 2.0),
                "above_ma20": False,
                "above_ma50": True,
                "above_ma250": True,
            },
        ],
        "breadth": {
            "advancers": 3180,
            "decliners": 1790,
            "unchanged": 172,
            "limit_up_count": 64,
            "limit_down_count": 6,
            "turnover_cny_bn": 1465.8,
            "turnover_vs_5d_pct": 0.118,
            "csi300_above_ma20_pct": 0.67,
            "csi300_above_ma50_pct": 0.58,
            "csi300_above_ma250_pct": 0.63,
        },
        "overseas": [
            {"symbol": "FTSE.A50", "name": "富时A50", "value": 13482.5, "change_pct": 0.0042},
            {"symbol": "NDX", "name": "纳斯达克", "value": 19120.4, "change_pct": 0.0068},
            {"symbol": "SPX", "name": "标普500", "value": 5942.1, "change_pct": 0.0045},
            {"symbol": "HXC", "name": "纳斯达克金龙", "value": 7128.0, "change_pct": 0.0115},
            {"symbol": "USDCNH", "name": "离岸人民币", "value": 7.184, "change_pct": -0.0014},
        ],
        "sector_alerts": [
            {
                "industry": "电力设备",
                "peer": "海外新能源指数",
                "change_pct": 0.021,
                "note": "隔夜海外新能源板块走强，观察早盘竞价承接",
            },
            {
                "industry": "有色金属",
                "peer": "伦铜主力合约",
                "change_pct": 0.013,
                "note": "工业金属夜盘小幅收涨",
            },
        ],
    }

    pitfall_calendar: dict[str, object] = {
        "status": "ok",
        "alerts": [
            {
                "symbol": "999003.SH",
                "name": "明川汽车",
                "kind": "earnings",
                "severity": "medium",
                "date": "2026-11-06",
                "title": "业绩说明会窗口",
                "detail": "拟于次一交易日盘后召开三季报业绩说明会，留意早盘竞价及盘中波动扩大。",
            },
            {
                "symbol": "999009.SH",
                "name": "青梧生物",
                "kind": "unlock",
                "severity": "high",
                "date": "2026-11-09",
                "title": "限售股解禁提示",
                "detail": "约占总股本 4.2% 的限售股将于下周初上市流通，该标的已进入纸面退出名单。",
            },
        ],
    }

    brief = build_brief(
        demo.cycle_root / DEMO_AS_OF,
        100_000.0,
        near_miss_floor=60.0,
        scoring_v2_path=demo.scoring_v2,
        market_pulse=market_pulse,
        pitfall_calendar=pitfall_calendar,
    )

    spec_map = {str(spec["symbol"]): spec for spec in DEMO_STOCKS}
    screen_map = (
        picker_data.screen_results
        if picker_data is not None and hasattr(picker_data, "screen_results")
        else {}
    )
    luk_notes = {
        "trigger": "EMA9/21 多头排列，放量收复整理平台中枢",
        "setup": "强势趋势内缩量盘整，等待突破确认",
        "leader_no_base": "中期动量较强但缺乏紧凑整理平台",
        "sideways": "箱体震荡区间内，趋势方向尚不明确",
        "downtrend": "位于关键均线下方，保持观望或执行退出",
    }

    for group_key in ("targets", "near_miss", "paper_exits"):
        for item in brief[group_key]:  # type: ignore[index]
            sym = str(item["symbol"])
            spec = spec_map.get(sym, {})
            prev = float(item["previous_close"]) if item.get("previous_close") else None
            profile = str(spec.get("profile", "sideways"))
            state = profile if profile in {"trigger", "setup", "leader_no_base"} else "avoid"
            stop_pct = 0.048 if state == "trigger" else 0.056 if state == "setup" else 0.075
            screen_row = screen_map.get(sym) if isinstance(screen_map, Mapping) else None
            if screen_row is not None and getattr(screen_row, "state", None):
                state = str(screen_row.state)
            item["luk_setup"] = {
                "state": state,
                "stop_price": round(prev * (1.0 - stop_pct), 2) if prev else None,
                "stop_pct": stop_pct,
                "confluence": 3 if state == "trigger" else 2 if state == "setup" else 0,
                "reward_r": 2.6 if state == "trigger" else 2.1 if state == "setup" else None,
                "base_days": 28 if state in {"trigger", "setup"} else None,
                "trigger_note": luk_notes.get(profile, ""),
            }
            name = str(item.get("name", ""))
            rev_yoy = spec.get("rev_yoy", 0.0)
            prof_yoy = spec.get("profit_yoy", 0.0)
            if sym == "999009.SH":
                item["overnight_announcements"] = {
                    "status": "alert",
                    "items": [
                        {
                            "title": f"{name}关于部分限售股份上市流通的提示性公告",
                            "published_at": f"{DEMO_AS_OF} 19:20",
                            "source": "cninfo_notice",
                            "polarity": "negative",
                            "url": "",
                            "summary": "本次解除限售股份占总股本约 4.2%，上市流通日为下一周首个交易日。",
                        }
                    ],
                }
            elif sym in {"999001.SH", "999002.SH", "999003.SH"}:
                item["overnight_announcements"] = {
                    "status": "ok",
                    "items": [
                        {
                            "title": f"{name}三季报要点跟踪：营收同比 +{rev_yoy}%，净利同比 +{prof_yoy}%",
                            "published_at": f"{DEMO_AS_OF} 18:15",
                            "source": "cninfo_notice",
                            "polarity": "positive",
                            "url": "",
                            "summary": "毛利率与经营性现金流保持平稳，未见监管问询或重大减持提示。",
                        }
                    ],
                }
            else:
                item["overnight_announcements"] = {"status": "clear", "items": []}

    # Sample 09:25 call auction quotes illustrating normal, strong volume, and weak relative gap
    sample_multipliers = {
        "999001.SH": (1.012, 68_000_000.0, 420_000_000.0),  # +1.2% gap, volume surge (16.2%)
        "999002.SH": (1.006, 22_000_000.0, 310_000_000.0),  # +0.6% clean normal open
        "999003.SH": (0.982, 18_000_000.0, 290_000_000.0),  # -1.8% gap, weak_vs_index (-2.22%)
        "999007.SH": (1.003, 9_500_000.0, 180_000_000.0),   # near miss normal
        "999008.SH": (1.008, 12_000_000.0, 210_000_000.0),  # near miss normal
    }
    sample_quotes: list[dict[str, object]] = []
    for item in [*brief["targets"], *brief["near_miss"]]:  # type: ignore[index]
        sym = str(item["symbol"])
        prev = item.get("previous_close")
        if prev is None or sym not in sample_multipliers:
            continue
        mult, auc_to, avg_to = sample_multipliers[sym]
        sample_quotes.append(
            {
                "symbol": sym,
                "price": f"{round(float(prev) * mult, 2):.2f}",
                "auction_turnover": auc_to,
                "avg_turnover_20d": avg_to,
            }
        )

    auction = evaluate_auction(brief, sample_quotes, benchmark_gap_pct=0.0042)
    return {"brief": brief, "auction": auction}


def demo_premarket_context(
    demo: DemoPaths, picker_data: PickerData | None = None
) -> dict[str, object]:
    """Compact `/api/premarket-context` payload consumed by `/picks` in demo mode."""
    bundle = demo_premarket_bundle(demo, picker_data)
    brief = bundle["brief"]
    auction = bundle.get("auction")
    by_symbol = (
        {str(c["symbol"]): c for c in auction.get("checks", [])}  # type: ignore[union-attr]
        if isinstance(auction, Mapping)
        else {}
    )
    return {
        "status": "ok",
        "signal_date": brief["signal_date"],  # type: ignore[index]
        "market_pulse": brief.get("market_pulse") or {"status": "unavailable"},  # type: ignore[union-attr]
        "pitfall_calendar": brief.get("pitfall_calendar")  # type: ignore[union-attr]
        or {"status": "not_checked", "alerts": []},
        "auction": (
            {
                "signal_date": auction.get("signal_date"),
                "benchmark_gap_pct": auction.get("benchmark_gap_pct"),
                "near_limit_pct": auction.get("near_limit_pct"),
                "large_gap_pct": auction.get("large_gap_pct"),
                "by_symbol": by_symbol,
            }
            if isinstance(auction, Mapping)
            else None
        ),
    }
