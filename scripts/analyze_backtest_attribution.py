"""Read-only re-evaluation of the formal CSI 300 backtest.

Restates the benchmark with the CSI 300 total-return index, separates market
exposure from stock selection, measures return concentration, regresses daily
returns on CSI style indices, and reports sector concentration of the holdings
reconstructed from the trade ledger. Nothing in the formal run, the paper
account or the evidence chain is modified.

Index and industry data come from AkShare on the first run and are cached as
CSV; ``--offline`` refuses to touch the network.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.reports.backtest_attribution import (  # noqa: E402
    annualized_return,
    beta_alpha_correlation,
    blended_benchmark,
    capture_ratios,
    circular_block_bootstrap,
    deflated_sharpe_ratio,
    drop_best_days,
    growth,
    herfindahl,
    ols,
    percentile,
    probabilistic_sharpe_ratio,
    sharpe_ratio,
    simple_returns,
    summarize,
)

DEFAULT_RUN_DIR = ROOT / "outputs" / "csi300_research" / "hfq-formal-20260713"
INDEX_NAMES = {
    "H00300": "CSI 300 Total Return",
    "000300": "CSI 300 (price)",
    "000922": "CSI Dividend",
    "H30269": "CSI Dividend Low Volatility",
    "000919": "CSI 300 Value",
    "000918": "CSI 300 Growth",
    "000852": "CSI 1000",
}
INDEX_START = "20210101"
RALLY_WINDOW = ("2024-09-15", "2024-10-31")
SHENWAN_STANDARD_CODE = "008003"
DSR_TRIALS = (1, 7, 20, 50, 100)
DSR_SHARPE_STD = (0.25, 0.5, 1.0)
HEADLINE_TRIALS = 7
HEADLINE_SHARPE_STD = 0.5
RISK_FREE_SENSITIVITY = 0.02

# Full-sample variants documented in AGENTS.md / git history before the
# formal hfq run. Each was evaluated on the same 2021-06-15..2026-07-13 window.
DOCUMENTED_VARIANTS = [
    {"commit": "7159c3c", "date": "2026-07-11", "variant": "dual-price scored baseline, no drawdown control",
     "total_return": 1.0409, "max_drawdown": 0.1203, "sharpe": None},
    {"commit": "7159c3c", "date": "2026-07-11", "variant": "simple 10% liquidation configuration",
     "total_return": 0.0480, "max_drawdown": 0.1049, "sharpe": None},
    {"commit": "f7f9eed", "date": "2026-07-12", "variant": "staged 8%/10% control with shadow-NAV 8%/6% recovery",
     "total_return": 1.0717, "max_drawdown": 0.0934, "sharpe": 1.60},
    {"commit": "0210094", "date": "2026-07-12", "variant": "dividend-tax lots, 10% liquidation trigger",
     "total_return": None, "max_drawdown": 0.10592, "sharpe": None},
    {"commit": "0210094", "date": "2026-07-12", "variant": "dividend-tax lots, 9% liquidation trigger",
     "total_return": 1.0553, "max_drawdown": 0.097278, "sharpe": 1.61},
    {"commit": "d398633", "date": "2026-07-13", "variant": "qfq signal prices (rejected)",
     "total_return": 1.4259, "max_drawdown": None, "sharpe": None},
    {"commit": "d398633", "date": "2026-07-13", "variant": "hfq signal prices (formal run analysed here)",
     "total_return": 1.1830, "max_drawdown": 0.0965, "sharpe": 1.71},
]

PARAMETER_PROVENANCE = [
    {"parameter": "buy_threshold = 70", "introduced": "2026-06-22 (61fc4dc)",
     "full_sample_informed": False,
     "note": "Set with the scored baseline before any CSI 300 result existed; unchanged since."},
    {"parameter": "min_confidence = 0.8", "introduced": "2026-07-04 (8a0088b)",
     "full_sample_informed": "unclear",
     "note": "Added after the STAR30 diagnostic runs, before the CSI 300 data path existed; "
             "not tuned on CSI 300, but chosen by the same researcher after seeing STAR30 behaviour."},
    {"parameter": "broad_market_drop_threshold = 15 names falling > 3%", "introduced": "2026-06-22 (716a7ff)",
     "full_sample_informed": False,
     "note": "Sized for the 30-stock STAR fixture (half the universe) and never rescaled for 300 names "
             "(5% of the universe). It is the main driver of the low exposure analysed in this report."},
    {"parameter": "reduce at 8% / recover at 8% and 6% (shadow NAV)", "introduced": "2026-07-12 (f7f9eed)",
     "full_sample_informed": True,
     "note": "Designed after the 2026-07-11 full-sample run showed 12.03% drawdown for the unrestricted "
             "baseline and 4.80% return for a simple 10% liquidation rule."},
    {"parameter": "liquidate at 9% (separate from the 10% limit)", "introduced": "2026-07-12 (0210094)",
     "full_sample_informed": True,
     "note": "Chosen after a full-sample tax-aware rerun breached the 10% limit with 10.592% drawdown."},
    {"parameter": "max_position_weight = 8%", "introduced": "2026-06-16 (911bb2d)",
     "full_sample_informed": False,
     "note": "Present in the initial scaffold."},
    {"parameter": "hfq signal-price adjustment", "introduced": "2026-07-13 (d398633)",
     "full_sample_informed": "partly",
     "note": "Chosen for an engineering reason (qfq rewrites history), but the 142.59% qfq result was "
             "seen first; the switch lowered the headline, so it is not a favourable selection."},
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--execution-prices", help="unadjusted daily.csv used by the formal run")
    parser.add_argument("--index-cache-dir", default=str(ROOT / "data" / "raw" / "index_history"))
    parser.add_argument("--industry-cache", default=str(ROOT / "data" / "raw" / "industry" / "sw_industry_cninfo.csv"))
    parser.add_argument("--membership-snapshot", help="CSI 300 constituent weights CSV for the sector reference")
    parser.add_argument("--output", default=str(ROOT / "outputs" / "research" / "backtest_attribution" / "hfq-formal-20260713.json"))
    parser.add_argument("--offline", action="store_true", help="fail instead of fetching missing cache files")
    parser.add_argument("--bootstrap-replications", type=int, default=5000)
    parser.add_argument("--block-length", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260713)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    pnl = json.loads((run_dir / "pnl_curve.json").read_text())
    dates = pnl["dates"]
    report_path = run_dir / "risk_controlled" / "run_report.json"
    report_sha = _sha256(report_path)
    if report_sha != pnl["inputs"]["risk_controlled_report"]["sha256"]:
        raise SystemExit("risk_controlled run_report.json does not match the hash recorded in pnl_curve.json")
    sections = read_report_sections(report_path, {"equity_curve", "trades", "corporate_actions", "inputs", "summary"})
    curve = sections["equity_curve"]
    if [point["trade_date"] for point in curve] != dates:
        raise SystemExit("equity curve dates differ from pnl_curve.json")
    for point, value in zip(curve, pnl["series"]["risk_controlled"]["equity"]):
        if abs(point["equity"] - value) > 1e-6:
            raise SystemExit("equity curve values differ from pnl_curve.json")

    end = dates[-1].replace("-", "")
    index_dir = Path(args.index_cache_dir)
    indices: dict[str, list[float]] = {}
    index_bars: dict[str, dict[str, tuple[float | None, float]]] = {}
    index_files: dict[str, dict[str, object]] = {}
    for code in INDEX_NAMES:
        path, bars = load_index(code, index_dir, INDEX_START, end, args.offline)
        missing = [day for day in dates if day not in bars]
        if missing:
            raise SystemExit(f"{code} is missing {len(missing)} backtest dates, first {missing[0]}")
        index_bars[code] = bars
        indices[code] = simple_returns([bars[day][1] for day in dates])
        index_files[code] = {"path": str(path), "sha256": _sha256(path)}

    strategy = simple_returns([point["equity"] for point in curve])
    baseline = simple_returns(pnl["series"]["baseline"]["equity"])
    sina_price = simple_returns(pnl["series"]["csi300"]["equity"])
    exposure = [point["positions_value"] / point["equity"] for point in curve]
    prior_exposure = exposure[:-1]
    return_dates = dates[1:]

    tr = indices["H00300"]
    beta_stats = beta_alpha_correlation(strategy, tr)
    beta_matched = blended_benchmark(tr, beta_stats["beta"])
    exposure_matched = blended_benchmark(tr, prior_exposure)
    # H00300 has no published open, so the open->close leg comes from 000300 and
    # the overnight leg (which also carries the dividend difference) is the rest.
    intraday = [index_bars["000300"][day][1] / index_bars["000300"][day][0] - 1 for day in return_dates]
    overnight = [(1 + r) / (1 + g) - 1 for r, g in zip(tr, intraday)]
    open_trade_matched = [
        (1 + w0 * on) * (1 + w1 * g) - 1
        for w0, w1, on, g in zip(prior_exposure, exposure[1:], overnight, intraday)
    ]

    payload: dict[str, object] = {
        "schema_version": 1,
        "scope": "read-only re-evaluation of the formal CSI 300 hfq backtest; no strategy, policy, "
                 "paper account or evidence file is modified",
        "period": {"start": dates[0], "end": dates[-1], "return_days": len(strategy)},
        "conventions": {
            "periods_per_year": 252,
            "risk_free_rate": "0 unless stated (matches the formal report; idle cash earns nothing in the backtest)",
            "exposure": "positions_value / equity at the prior close",
        },
        "inputs": {
            "pnl_curve": {"path": str(run_dir / "pnl_curve.json"), "sha256": _sha256(run_dir / "pnl_curve.json")},
            "risk_controlled_report": {"path": str(report_path), "sha256": report_sha},
            "indices": index_files,
        },
        "code": _git_state(),
    }
    payload["look_ahead_diagnostics"] = look_ahead_section(
        dates, curve, sections["trades"], read_broad_market_counts(report_path),
        intraday, prior_exposure, exposure, strategy, tr, open_trade_matched,
    )
    payload["benchmark_restatement"] = benchmark_restatement(strategy, baseline, indices, sina_price)
    payload["exposure_and_beta"] = exposure_section(
        strategy, tr, prior_exposure, exposure, beta_stats, beta_matched, exposure_matched, open_trade_matched
    )
    payload["concentration"] = concentration_section(
        strategy, tr, beta_matched, open_trade_matched, return_dates, args
    )
    payload["style_attribution"] = style_section(strategy, indices, prior_exposure)

    execution_prices = Path(args.execution_prices or sections["inputs"]["execution_prices"])
    payload["holdings"] = holdings_section(
        dates, curve, sections, execution_prices, Path(args.industry_cache),
        Path(args.membership_snapshot) if args.membership_snapshot else None, args.offline,
    )
    payload["inputs"]["execution_prices"] = {"path": str(execution_prices), "sha256": _sha256(execution_prices)}
    payload["documented_full_sample_variants"] = DOCUMENTED_VARIANTS
    payload["parameter_provenance"] = PARAMETER_PROVENANCE

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(_round(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(f"attribution_path={output}")
    return 0


def read_report_sections(path: Path, keys: set[str]) -> dict[str, object]:
    """Parse only the requested top-level keys of a pretty-printed report.

    The formal reports are ~600 MB; the needed sections are a few MB, so the
    file is scanned line by line and only those sections are JSON-decoded.
    """
    sections: dict[str, object] = {}
    current: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if current is not None:
            text = "".join(buffer).rstrip().rstrip(",")
            sections[current] = json.loads("{" + text + "}")[current]

    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.startswith('  "') or line.startswith("}"):
                flush()
                current = None
                buffer = []
                if line.startswith('  "'):
                    key = line.split('"', 2)[1]
                    if key in keys:
                        current = key
                        buffer = [line]
            elif current is not None:
                buffer.append(line)
    missing = keys - sections.keys()
    if missing:
        raise SystemExit(f"report is missing sections: {sorted(missing)}")
    return sections


def load_index(
    code: str, cache_dir: Path, start: str, end: str, offline: bool
) -> tuple[Path, dict[str, tuple[float | None, float]]]:
    """Daily (open, close) for a CSI index; open is None where CSI publishes none."""
    path = cache_dir / f"csindex_{code}_{start}_{end}.csv"
    if not path.exists():
        if offline:
            raise SystemExit(f"missing cached index file {path} (run once without --offline)")
        import akshare as ak

        frame = ak.stock_zh_index_hist_csindex(symbol=code, start_date=start, end_date=end)
        rows = sorted(
            (str(day), "" if math.isnan(float(day_open)) else float(day_open), float(close))
            for day, day_open, close in zip(frame["日期"], frame["开盘"], frame["收盘"])
        )
        cache_dir.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["trade_date", "open", "close"])
            writer.writerows(rows)
    with path.open(encoding="utf-8") as handle:
        return path, {
            row["trade_date"]: (float(row["open"]) if row["open"] else None, float(row["close"]))
            for row in csv.DictReader(handle)
        }


def read_broad_market_counts(path: Path) -> dict[str, float]:
    """Dates on which the engine raised its broad-market-drop warning, with the count.

    ``risk_warnings`` holds ~360k entries; scanning its lines avoids decoding
    the whole section. Each warning lists observed_value, rule and trade_date
    in that (sorted-key) order.
    """
    counts: dict[str, float] = {}
    inside = False
    observed = rule = None
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.startswith('  "'):
                if inside:
                    break
                inside = line.startswith('  "risk_warnings"')
                continue
            if not inside:
                continue
            stripped = line.strip()
            if stripped.startswith('"observed_value"'):
                observed = stripped.split(":", 1)[1].strip().rstrip(",")
            elif stripped.startswith('"rule"'):
                rule = stripped.split('"')[3]
            elif stripped.startswith('"trade_date"') and rule == "broad_market_drop_gt_3pct_count":
                counts[stripped.split('"')[3]] = float(observed)
    if not counts:
        raise SystemExit("no broad_market_drop_gt_3pct_count warnings found in the report")
    return counts


def look_ahead_section(dates, curve, trades, hot_counts, intraday, prior_exposure, exposure, strategy, tr,
                       open_trade_matched):
    """Test whether trades filled at day D's open depend on day D's close data.

    The broad-market rule fires when more than 15 tracked names fall over 3%
    by the close. If decisions only used the prior close, the share of trading
    days that turn out "hot" should be similar for days with and without
    trades, and the open-trade exposure change should be uncorrelated with the
    index's open->close move.
    """
    hot = {day for day in dates if hot_counts.get(day, 0) > 15}
    buys: dict[str, str] = {}
    sells: dict[str, str] = {}
    for trade in trades:
        target = buys if trade["action"] == "buy" else sells
        target.setdefault(trade["trade_date"], trade["signal_date"])

    def tally(days: dict[str, str]) -> dict[str, int]:
        return {
            "trade_days": len(days),
            "execution_day_hot": sum(1 for day in days if day in hot),
            "signal_day_hot": sum(1 for signal in days.values() if signal in hot),
        }

    return_dates = dates[1:]
    hot_intraday = [g for day, g in zip(return_dates, intraday) if day in hot]
    calm_intraday = [g for day, g in zip(return_dates, intraday) if day not in hot]
    gains = [(w1 - w0) * g for w0, w1, g in zip(prior_exposure, exposure[1:], intraday)]
    mean_gain = sum(gains) / len(gains)
    std_gain = math.sqrt(sum((v - mean_gain) ** 2 for v in gains) / (len(gains) - 1))
    return {
        "finding": "Risk inputs are looked up by execution date (portfolio_research_runner.py: "
                   "risk_by_key.get((trade_date, symbol)) and _dynamic_risk_input(close, ...)) while "
                   "fills use that date's open. The broad-market rule therefore uses the execution "
                   "day's own close to decide trades filled at its open.",
        "hot_rule": "engine warning broad_market_drop_gt_3pct_count (> 15 tracked names fell > 3%)",
        "hot_days": len(hot),
        "total_days": len(dates),
        "closes_invested_on_hot_days": sum(1 for p in curve if p["trade_date"] in hot and p["positions_value"] > 0),
        "buys": tally(buys),
        "sells": tally(sells),
        "csi300_open_to_close_mean": {
            "hot_days": sum(hot_intraday) / len(hot_intraday),
            "calm_days": sum(calm_intraday) / len(calm_intraday),
        },
        "open_trade_timing_gain": {
            "definition": "(post-open exposure - prior-close exposure) * CSI 300 open->close return",
            "mean_daily": mean_gain,
            "t_stat": mean_gain / std_gain * math.sqrt(len(gains)),
            "compounded_multiple": growth(gains),
        },
        "strategy_multiple": growth(strategy),
        "H00300_multiple": growth(tr),
        "index_on_same_exposure_path_multiple": growth(open_trade_matched),
    }


def benchmark_restatement(strategy, baseline, indices, sina_price) -> dict[str, object]:
    tr = indices["H00300"]
    price = indices["000300"]
    out = {
        "risk_controlled": summarize(strategy),
        "unrestricted_baseline": summarize(baseline),
        "csi300_price_000300": summarize(price),
        "csi300_total_return_H00300": summarize(tr),
        "formal_report_price_benchmark_sina": summarize(sina_price),
    }
    s, p, t = growth(strategy), growth(price), growth(tr)
    out["excess_total_return"] = {
        "vs_price_index": s - p,
        "vs_total_return_index": s - t,
        "overstatement_points": t - p,
    }
    out["excess_annualized_return"] = {
        "vs_price_index": annualized_return(strategy) - annualized_return(price),
        "vs_total_return_index": annualized_return(strategy) - annualized_return(tr),
    }
    return out


def exposure_section(
    strategy, tr, prior_exposure, exposure, beta_stats, beta_matched, exposure_matched, open_trade_matched
):
    invested = [index for index, weight in enumerate(prior_exposure) if weight > 0]
    pick = lambda series: [series[index] for index in invested]  # noqa: E731
    sorted_exposure = sorted(exposure)
    selection = [s - e for s, e in zip(strategy, exposure_matched)]
    return {
        "exposure": {
            "mean": sum(exposure) / len(exposure),
            "median": sorted_exposure[len(sorted_exposure) // 2],
            "share_of_closes_fully_in_cash": sum(1 for value in exposure if value == 0) / len(exposure),
            "share_of_return_days_starting_in_cash": 1 - len(invested) / len(prior_exposure),
            "mean_when_invested": sum(pick(prior_exposure)) / len(invested),
        },
        "vs_H00300": {
            **beta_stats,
            "alpha_annualized": beta_stats["alpha_daily"] * 252,
            **capture_ratios(strategy, tr),
        },
        "beta_matched_benchmark": {
            "definition": "beta * H00300 + (1 - beta) * cash at 0%, rebalanced daily",
            "beta": beta_stats["beta"],
            "summary": summarize(beta_matched),
            "excess_total_return": growth(strategy) - growth(beta_matched),
            "excess_annualized_return": annualized_return(strategy) - annualized_return(beta_matched),
        },
        "exposure_matched_benchmark": {
            "definition": "prior-close exposure * H00300 + rest in cash: same timing path, index instead of picks",
            "summary": summarize(exposure_matched),
            "excess_total_return": growth(strategy) - growth(exposure_matched),
            "excess_annualized_return": annualized_return(strategy) - annualized_return(exposure_matched),
            "selection_series_sharpe": sharpe_ratio(selection),
        },
        "open_trade_exposure_matched_benchmark": {
            "definition": "overnight leg at prior-close exposure, open->close leg at post-open exposure: "
                          "the backtest's actual exposure path, including trades filled at the open, "
                          "applied to the index",
            "summary": summarize(open_trade_matched),
            "excess_total_return": growth(strategy) - growth(open_trade_matched),
        },
        "invested_days_only": {
            "days": len(invested),
            "strategy_growth": growth(pick(strategy)),
            "H00300_growth": growth(pick(tr)),
            "exposure_matched_growth": growth(pick(exposure_matched)),
            "excess_vs_H00300": growth(pick(strategy)) - growth(pick(tr)),
            "excess_vs_exposure_matched": growth(pick(strategy)) - growth(pick(exposure_matched)),
            "beta_vs_H00300": beta_alpha_correlation(pick(strategy), pick(tr))["beta"],
            "correlation_vs_H00300": beta_alpha_correlation(pick(strategy), pick(tr))["correlation"],
        },
        "timing_vs_selection_total_return": {
            "H00300": growth(tr) - 1,
            "strategy": growth(strategy) - 1,
            "prior_close_path": {
                "index_on_path": growth(exposure_matched) - 1,
                "timing_effect": growth(exposure_matched) - growth(tr),
                "selection_effect": growth(strategy) - growth(exposure_matched),
            },
            "open_trade_path": {
                "index_on_path": growth(open_trade_matched) - 1,
                "timing_effect": growth(open_trade_matched) - growth(tr),
                "selection_effect": growth(strategy) - growth(open_trade_matched),
            },
        },
    }


def concentration_section(strategy, tr, beta_matched, open_trade_matched, return_dates, args):
    total_log = math.log(growth(strategy))
    by_year: dict[str, dict[str, float]] = {}
    for year in sorted({day[:4] for day in return_dates}):
        idx = [i for i, day in enumerate(return_dates) if day.startswith(year)]
        s = [strategy[i] for i in idx]
        by_year[year] = {
            "days": len(idx),
            "strategy": growth(s) - 1,
            "H00300": growth([tr[i] for i in idx]) - 1,
            "beta_matched": growth([beta_matched[i] for i in idx]) - 1,
            "open_trade_matched": growth([open_trade_matched[i] for i in idx]) - 1,
            "share_of_total_log_return": math.log(growth(s)) / total_log,
        }

    start, end = RALLY_WINDOW
    in_window = [start <= day <= end for day in return_dates]
    keep = lambda series: [v for v, flag in zip(series, in_window) if not flag]  # noqa: E731
    inside = lambda series: [v for v, flag in zip(series, in_window) if flag]  # noqa: E731
    ranked = sorted(range(len(strategy)), key=lambda i: (-strategy[i], i))

    selection = [s - e for s, e in zip(strategy, open_trade_matched)]
    active_beta = [s - b for s, b in zip(strategy, beta_matched)]
    stats = {
        "strategy_annualized_return": lambda s, t, e, b: annualized_return(s),
        "strategy_sharpe": lambda s, t, e, b: sharpe_ratio(s),
        "excess_annualized_vs_H00300": lambda s, t, e, b: annualized_return(s) - annualized_return(t),
        "excess_annualized_vs_beta_matched": lambda s, t, e, b: annualized_return(s) - annualized_return(b),
        "excess_annualized_vs_open_trade_matched": lambda s, t, e, b: annualized_return(s) - annualized_return(e),
    }
    samples = circular_block_bootstrap(
        [strategy, tr, open_trade_matched, beta_matched],
        stats,
        block_length=args.block_length,
        replications=args.bootstrap_replications,
        seed=args.seed,
    )
    point = {name: fn(strategy, tr, open_trade_matched, beta_matched) for name, fn in stats.items()}
    bootstrap = {
        "method": "circular block bootstrap, joint resampling of aligned daily series",
        "block_length": args.block_length,
        "replications": args.bootstrap_replications,
        "seed": args.seed,
        "statistics": {
            name: {
                "point": point[name],
                "ci_2_5": percentile(values, 0.025),
                "ci_97_5": percentile(values, 0.975),
                "share_at_or_below_zero": sum(1 for v in values if v <= 0) / len(values),
            }
            for name, values in samples.items()
        },
    }

    def dsr_grid(series):
        return [deflated_sharpe_ratio(series, n, sd) for n in DSR_TRIALS for sd in DSR_SHARPE_STD]

    return {
        "by_calendar_year": by_year,
        "rally_window": {
            "start": start,
            "end": end,
            "days": sum(in_window),
            "strategy_return_inside": growth(inside(strategy)) - 1,
            "H00300_return_inside": growth(inside(tr)) - 1,
            "strategy_excluding": summarize(keep(strategy)),
            "H00300_excluding": summarize(keep(tr)),
            "beta_matched_excluding": summarize(keep(beta_matched)),
            "excess_total_vs_H00300_excluding": growth(keep(strategy)) - growth(keep(tr)),
            "excess_total_vs_beta_matched_excluding": growth(keep(strategy)) - growth(keep(beta_matched)),
        },
        "best_days": {
            "full_multiple": growth(strategy),
            **{f"multiple_without_best_{n}": growth(drop_best_days(strategy, n)) for n in (5, 10, 20)},
            "best_10": [{"date": return_dates[i], "return": strategy[i]} for i in ranked[:10]],
        },
        "bootstrap": bootstrap,
        "deflated_sharpe": {
            "documented_full_sample_variants": len(DOCUMENTED_VARIANTS),
            "headline": {
                "trials": HEADLINE_TRIALS,
                "sharpe_std_annual": HEADLINE_SHARPE_STD,
                "strategy": deflated_sharpe_ratio(strategy, HEADLINE_TRIALS, HEADLINE_SHARPE_STD),
                "selection_vs_open_trade_matched": deflated_sharpe_ratio(selection, HEADLINE_TRIALS, HEADLINE_SHARPE_STD),
                "active_vs_beta_matched": deflated_sharpe_ratio(active_beta, HEADLINE_TRIALS, HEADLINE_SHARPE_STD),
            },
            "psr_vs_zero": {
                "strategy": probabilistic_sharpe_ratio(strategy),
                "selection_vs_open_trade_matched": probabilistic_sharpe_ratio(selection),
                "active_vs_beta_matched": probabilistic_sharpe_ratio(active_beta),
            },
            "grid_strategy": dsr_grid(strategy),
            "grid_selection_vs_open_trade_matched": dsr_grid(selection),
            "sharpe_rf_2pct": sharpe_ratio(strategy, RISK_FREE_SENSITIVITY),
        },
    }


def style_section(strategy, indices, prior_exposure):
    r = indices
    factors = {
        "market_H00300": r["H00300"],
        "value_minus_growth": [a - b for a, b in zip(r["000919"], r["000918"])],
        "small_minus_large": [a - b for a, b in zip(r["000852"], r["000300"])],
        "dividend_lowvol_minus_market": [a - b for a, b in zip(r["H30269"], r["000300"])],
        "dividend_minus_market": [a - b for a, b in zip(r["000922"], r["000300"])],
    }
    invested = [i for i, w in enumerate(prior_exposure) if w > 0]
    subset = lambda series: [series[i] for i in invested]  # noqa: E731
    without_dividend = {k: v for k, v in factors.items() if k != "dividend_minus_market"}
    names = list(factors)
    return {
        "univariate_vs_index": {
            f"{code} {INDEX_NAMES[code]}": beta_alpha_correlation(strategy, series) for code, series in r.items()
        },
        "factor_correlations": {
            a: {b: beta_alpha_correlation(factors[a], factors[b])["correlation"] for b in names} for a in names
        },
        "regressions": {
            "market_only": ols(strategy, {"market_H00300": factors["market_H00300"]}, newey_west_lags=5),
            "market_plus_styles": ols(strategy, without_dividend, newey_west_lags=5),
            "market_plus_styles_with_dividend": ols(strategy, factors, newey_west_lags=5),
            "market_plus_styles_invested_days": ols(
                subset(strategy), {k: subset(v) for k, v in without_dividend.items()}, newey_west_lags=5
            ),
        },
        "notes": "Spreads use price indices on both legs; the market leg is total return. "
                 "Intercepts are daily; multiply by 252 for an annual alpha. Newey-West lag 5.",
    }


def holdings_section(dates, curve, sections, execution_prices, industry_cache, membership_snapshot, offline):
    trades = sections["trades"]
    actions = sections["corporate_actions"]
    events: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for action in actions:
        events[action["ex_date"]].append((0, action))
    for trade in trades:
        events[trade["trade_date"]].append((1, trade))

    symbols = sorted({t["symbol"] for t in trades})
    closes = _load_closes(execution_prices, set(symbols), set(dates))
    shares: dict[str, float] = {}
    last_close: dict[str, float] = {}
    previous_value: dict[str, float] = {}
    gross_pnl: dict[str, float] = defaultdict(float)
    window_pnl: dict[str, float] = defaultdict(float)
    daily: list[dict[str, float]] = []
    recon_errors: list[float] = []
    for day, point in zip(dates, curve):
        flows: dict[str, float] = defaultdict(float)
        for kind, event in sorted(events.get(day, []), key=lambda item: item[0]):
            if kind == 0:
                shares[event["symbol"]] = event["shares_after"]
                flows[event["symbol"]] += event["cash_delta"]
            else:
                shares[event["symbol"]] = event["position"]
                sign = -1.0 if event["action"] == "buy" else 1.0
                flows[event["symbol"]] += sign * event["notional"]
        for symbol in symbols:
            if (symbol, day) in closes:
                last_close[symbol] = closes[(symbol, day)]
        values = {s: n * last_close[s] for s, n in shares.items() if n}
        for symbol in set(values) | set(previous_value) | set(flows):
            pnl = values.get(symbol, 0.0) - previous_value.get(symbol, 0.0) + flows.get(symbol, 0.0)
            gross_pnl[symbol] += pnl
            if RALLY_WINDOW[0] <= day <= RALLY_WINDOW[1]:
                window_pnl[symbol] += pnl
        previous_value = values
        shares = {s: n for s, n in shares.items() if n}
        recon_errors.append(abs(sum(values.values()) - point["positions_value"]) / point["equity"])
        daily.append(values)

    industries = load_industries(sorted(set(symbols) | _snapshot_symbols(membership_snapshot)), industry_cache, offline)
    sector_of = lambda symbol, day: _industry_as_of(industries.get(symbol, []), day)  # noqa: E731

    sector_weight_sum: dict[str, float] = defaultdict(float)
    hhi_sector, hhi_stock, max_sector, counts = [], [], [], []
    invested_days = 0
    for day, values in zip(dates, daily):
        total = sum(values.values())
        if total <= 0:
            continue
        invested_days += 1
        by_sector: dict[str, float] = defaultdict(float)
        for symbol, value in values.items():
            by_sector[sector_of(symbol, day)] += value
        for sector, value in by_sector.items():
            sector_weight_sum[sector] += value / total
        hhi_sector.append(herfindahl(list(by_sector.values())))
        hhi_stock.append(herfindahl(list(values.values())))
        max_sector.append(max(by_sector.values()) / total)
        counts.append(len(values))

    def by_sector_pnl(pnl_map, day):
        out: dict[str, float] = defaultdict(float)
        for symbol, value in pnl_map.items():
            out[sector_of(symbol, day)] += value
        return dict(sorted(out.items(), key=lambda item: -item[1]))

    summary = sections["summary"]
    total_gross = sum(gross_pnl.values())
    # Sell notionals already net out dividend tax, so symbol P&L is gross of trading costs only.
    expected_gross = summary["ending_equity"] - summary["initial_cash"] + summary["total_trading_cost"]
    reference = _snapshot_sector_weights(membership_snapshot, industries) if membership_snapshot else None
    return {
        "method": "end-of-day shares rebuilt from trade 'position' fields and corporate-action 'shares_after', "
                  "valued at unadjusted closes (last close carried through suspensions); Shenwan level-1 "
                  "industry as of each date from CNInfo (earliest record used if none precedes the date)",
        "traded_symbols": len(symbols),
        "invested_days": invested_days,
        "positions_value_reconciliation": {
            "max_abs_error_share_of_equity": max(recon_errors),
            "mean_abs_error_share_of_equity": sum(recon_errors) / len(recon_errors),
        },
        "gross_pnl_reconciliation": {
            "sum_of_symbol_gross_pnl": total_gross,
            "equity_change_plus_trading_costs": expected_gross,
        },
        "holdings_count": {"mean": sum(counts) / len(counts), "max": max(counts), "min": min(counts)},
        "mean_stock_hhi": sum(hhi_stock) / len(hhi_stock),
        "mean_sector_hhi": sum(hhi_sector) / len(hhi_sector),
        "mean_max_sector_weight": sum(max_sector) / len(max_sector),
        "max_sector_weight_observed": max(max_sector),
        "mean_sector_weight_of_positions": dict(
            sorted(((k, v / invested_days) for k, v in sector_weight_sum.items()), key=lambda item: -item[1])
        ),
        "csi300_sector_weights_reference": reference,
        "gross_pnl_by_sector": by_sector_pnl(gross_pnl, dates[-1]),
        "rally_window_gross_pnl_by_sector": by_sector_pnl(window_pnl, RALLY_WINDOW[0]),
        "unclassified_symbols": sorted(s for s in symbols if not industries.get(s)),
    }


def load_industries(symbols: list[str], cache: Path, offline: bool) -> dict[str, list[tuple[str, str]]]:
    """Shenwan level-1 industry history per symbol, fetched once and cached."""
    rows: list[dict[str, str]] = []
    if cache.exists():
        with cache.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    known = {row["symbol"] for row in rows}
    missing = [s for s in symbols if s not in known]
    if missing:
        if offline:
            raise SystemExit(f"{len(missing)} symbols missing from industry cache {cache}")
        import akshare as ak

        cache.parent.mkdir(parents=True, exist_ok=True)
        new_file = not cache.exists()
        with cache.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["symbol", "change_date", "sw_level1"])
            if new_file:
                writer.writeheader()
            for symbol in missing:
                fetched = []
                for attempt in range(3):
                    try:
                        frame = ak.stock_industry_change_cninfo(
                            symbol=symbol[:6], start_date="20000101", end_date="20261231"
                        )
                        break
                    except Exception:  # provider hiccup: retry, then record as unclassified
                        frame = None
                        time.sleep(2 * (attempt + 1))
                if frame is not None and len(frame):
                    sw = frame[frame["分类标准编码"].astype(str) == SHENWAN_STANDARD_CODE]
                    fetched = [
                        {"symbol": symbol, "change_date": str(day)[:10], "sw_level1": str(name)}
                        for day, name in zip(sw["变更日期"], sw["行业门类"])
                    ]
                if not fetched:
                    fetched = [{"symbol": symbol, "change_date": "", "sw_level1": ""}]
                writer.writerows(fetched)
                handle.flush()
                rows.extend(fetched)
                time.sleep(0.3)
    history: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in rows:
        if row["sw_level1"]:
            history[row["symbol"]].append((row["change_date"], row["sw_level1"]))
    return {symbol: sorted(items) for symbol, items in history.items()}


def _industry_as_of(history: list[tuple[str, str]], day: str) -> str:
    if not history:
        return "Unclassified"
    current = history[0][1]
    for change_date, name in history:
        if change_date <= day:
            current = name
    return current


def _snapshot_symbols(path: Path | None) -> set[str]:
    if path is None:
        return set()
    with path.open(encoding="utf-8") as handle:
        return {row["symbol"] for row in csv.DictReader(handle)}


def _snapshot_sector_weights(path: Path, industries) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    as_of = rows[0]["as_of"]
    weights: dict[str, float] = defaultdict(float)
    for row in rows:
        weights[_industry_as_of(industries.get(row["symbol"], []), as_of)] += float(row["weight"])
    total = sum(weights.values())
    return {
        "as_of": as_of,
        "source": str(path),
        "weights": dict(sorted(((k, v / total) for k, v in weights.items()), key=lambda item: -item[1])),
    }


def _load_closes(path: Path, symbols: set[str], dates: set[str]) -> dict[tuple[str, str], float]:
    closes: dict[tuple[str, str], float] = {}
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["symbol"] in symbols and row["trade_date"] in dates and row["close"]:
                closes[(row["symbol"], row["trade_date"])] = float(row["close"])
    return closes


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_state() -> dict[str, object]:
    def run(*cmd: str) -> str:
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()

    return {
        "commit": run("git", "rev-parse", "HEAD"),
        "dirty": bool(run("git", "status", "--porcelain", "--", "scripts", "src")),
    }


def _round(value):
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {k: _round(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round(v) for v in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
