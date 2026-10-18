"""Cross-sectional factor study on the CSI 300 point-in-time panel.

Read-only research track. Inputs are the processed hfq features, the
point-in-time fundamentals and capital-flow proxy, and the historical
membership referenced by the paper pipeline state. Market cap comes from the
raw valuation records (总市值 / 流通市值) in the factor manifest chain;
Shenwan level-1 industries come from the attribution study's cache. The
counted strategy, frozen policy and evidence files are never modified.

Writes a JSON result and a Markdown report.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (SRC, ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from analyze_backtest_attribution import load_industries  # noqa: E402
from fintech_quant.research.factor_lab import FACTORS, run_study  # noqa: E402

MAIN = Path("/Users/yakou/Desktop/Vibe-Trading")
FEATURE_COLUMNS = ["symbol", "trade_date", "open", "close", "volume", "amount", "rsi14",
                   "macd_hist", "ma20", "ma60", "ma250"]
FUNDAMENTAL_COLUMNS = ["pe", "pb", "roe", "growth"]
FLOW_COLUMNS = ["price_volume_flow_signal", "cmf", "obv_momentum"]
DATE_RE = re.compile(r'"数据日期": "(\d{4}-\d{2}-\d{2})"')
MCAP_RE = re.compile(r'"总市值": ([0-9.eE+-]+)')
FLOAT_RE = re.compile(r'"流通市值": ([0-9.eE+-]+)')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pipeline-state",
                        default=str(MAIN / "data/paper/csi300_baseline/pipeline_state.json"))
    parser.add_argument("--industry-cache",
                        default=str(MAIN / "data/raw/industry/sw_industry_cninfo.csv"))
    parser.add_argument("--offline", action="store_true",
                        help="fail instead of fetching industries missing from the cache")
    parser.add_argument("--train-end", default="2024-06-30")
    parser.add_argument("--holdout-start", default="2024-07-01")
    parser.add_argument("--primary-horizon", type=int, default=5)
    parser.add_argument("--ridge-penalty", type=float, default=0.1)
    parser.add_argument("--stress-window", nargs=2, default=["2024-09-15", "2024-10-31"],
                        help="hold-out window removed in the combined-signal sensitivity view")
    parser.add_argument("--output-json",
                        default=str(MAIN / "outputs/research/factor_lab/factor_lab.json"))
    parser.add_argument("--report",
                        default=str(ROOT / f"docs/research/{date.today():%Y-%m-%d}-factor-lab.md"))
    args = parser.parse_args()

    state_path = Path(args.pipeline_state)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    signal_manifest = Path(state["manifests"]["signal_price"]["processed_manifest"])
    factor_manifest = Path(state["manifests"]["factor"]["processed_manifest"])
    membership_path = Path(state["membership"]["path"])
    _require_hfq(signal_manifest)

    features = pd.read_csv(signal_manifest.parent / "features.csv", usecols=FEATURE_COLUMNS)
    fundamentals = pd.read_csv(factor_manifest.parent / "fundamentals.csv",
                               usecols=["symbol", "available_date", *FUNDAMENTAL_COLUMNS])
    flows = pd.read_csv(factor_manifest.parent / "capital_flow.csv",
                        usecols=["symbol", "available_date", *FLOW_COLUMNS])
    calendar = pd.Index(sorted(features["trade_date"].unique()))
    symbols = pd.Index(sorted(features["symbol"].unique()))

    def wide(frame: pd.DataFrame, column: str, date_column: str) -> pd.DataFrame:
        return (frame.pivot(index=date_column, columns="symbol", values=column)
                .reindex(index=calendar, columns=symbols).astype(float))

    panel = {c: wide(features, c, "trade_date") for c in FEATURE_COLUMNS[2:]}
    panel |= {c: wide(fundamentals, c, "available_date") for c in FUNDAMENTAL_COLUMNS}
    panel |= {c: wide(flows, c, "available_date") for c in FLOW_COLUMNS}
    mcap, float_mcap, raw_runs = load_market_caps(factor_manifest, calendar, symbols)
    panel["float_mcap"] = float_mcap
    log_mcap = np.log(mcap.where(mcap > 0))

    universe = membership_frame(membership_path, calendar, symbols)
    member_symbols = sorted(symbols[universe.any().to_numpy()])
    industries = load_industries(member_symbols, Path(args.industry_cache), args.offline)
    industry = industry_frame(industries, calendar, symbols)

    study = run_study(panel, universe, industry, log_mcap, args.train_end, args.holdout_start,
                      primary_horizon=args.primary_horizon, ridge_penalty=args.ridge_penalty,
                      stress_window=tuple(args.stress_window))
    member = universe.to_numpy()
    study["inputs"] = {
        "pipeline_state": _file_ref(state_path),
        "signal_price_manifest": _file_ref(signal_manifest),
        "factor_manifest": _file_ref(factor_manifest),
        "membership": _file_ref(membership_path),
        "industry_cache": _file_ref(Path(args.industry_cache)),
        "market_cap_raw_runs": raw_runs,
        "git_sha": _git_sha(),
        "member_cells": int(member.sum()),
        "member_cells_missing_market_cap": int((member & ~np.isfinite(log_mcap.to_numpy())).sum()),
        "member_cells_unclassified_industry": int((member & industry.isna().to_numpy()).sum()),
        "symbols_without_market_cap": sorted(
            s for s in member_symbols if not np.isfinite(log_mcap[s]).any()),
    }
    study["settings"] = {
        "winsorize": "median +/- 3 x 1.4826 x MAD",
        "neutralize": "OLS residual on Shenwan level-1 dummies + z-scored log total market cap",
        "forward_return": "hfq open[T+1+h] / open[T+1] - 1 for the T-close signal",
        "ridge_penalty": args.ridge_penalty,
    }

    out = Path(args.output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(study, ensure_ascii=False, indent=2, default=_json_default) + "\n",
                   encoding="utf-8")
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(study, out), encoding="utf-8")
    print(f"wrote {out}\nwrote {report}")
    return 0


def _require_hfq(manifest: Path) -> None:
    request = json.loads(manifest.read_text(encoding="utf-8"))["request"]
    if request.get("adjust") != "hfq":
        raise SystemExit(f"signal-price manifest is not hfq: {manifest}")


def load_market_caps(factor_manifest: Path, calendar: pd.Index, symbols: pd.Index):
    """Total and float market cap per day from the raw valuation records.

    Later runs in the manifest chain override earlier ones for the same date.
    """
    chain = json.loads(factor_manifest.read_text(encoding="utf-8"))["request"]["raw_manifest_chain"]
    total: dict[tuple[str, str], float] = {}
    floating: dict[tuple[str, str], float] = {}
    runs = []
    for link in chain:
        run_dir = Path(link["path"]).parent / "fundamentals"
        runs.append({"path": link["path"], "sha256": link["sha256"]})
        for file in sorted(run_dir.glob("*.jsonl")):
            symbol = file.stem
            with file.open(encoding="utf-8") as handle:
                for line in handle:
                    day, cap = DATE_RE.search(line), MCAP_RE.search(line)
                    if day is None or cap is None:
                        continue
                    total[(symbol, day.group(1))] = float(cap.group(1))
                    fl = FLOAT_RE.search(line)
                    if fl is not None:
                        floating[(symbol, day.group(1))] = float(fl.group(1))

    def to_frame(values: dict[tuple[str, str], float]) -> pd.DataFrame:
        series = pd.Series(values)
        series.index = pd.MultiIndex.from_tuples(series.index, names=["symbol", "date"])
        return series.unstack("symbol").reindex(index=calendar, columns=symbols).astype(float)

    return to_frame(total), to_frame(floating), runs


def membership_frame(path: Path, calendar: pd.Index, symbols: pd.Index) -> pd.DataFrame:
    """True where the symbol is a member on the date (member_from <= T < member_to)."""
    frame = pd.DataFrame(False, index=calendar, columns=symbols)
    dates = calendar.to_numpy()
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["symbol"] not in frame.columns:
                continue
            end = row["member_to"] or "9999-12-31"
            active = (dates >= row["member_from"]) & (dates < end)
            frame.loc[active, row["symbol"]] = True
    return frame


def industry_frame(industries: dict[str, list[tuple[str, str]]], calendar: pd.Index,
                   symbols: pd.Index) -> pd.DataFrame:
    """Shenwan level-1 label as of each date; earliest record if none precedes the date."""
    frame = pd.DataFrame(None, index=calendar, columns=symbols, dtype=object)
    dates = calendar.to_numpy()
    for symbol, history in industries.items():
        if symbol not in frame.columns or not history:
            continue
        labels = np.full(len(dates), history[0][1], dtype=object)
        for change_date, name in history:
            labels[dates >= change_date] = name
        frame[symbol] = labels
    return frame


def _file_ref(path: Path) -> dict[str, object]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:  # not a checkout
        return None


def _json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    raise TypeError(type(value))


# ------------------------------------------------------------------------- report


def _f(value, digits: int = 3, pct: bool = False) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "n/a"
    return f"{value * 100:.{digits - 1}f}%" if pct else f"{value:.{digits}f}"


def render_report(study: dict, json_path: Path) -> str:
    h = str(study["primary_horizon"])
    mt = study["multiple_testing"]
    inputs = study["inputs"]
    factors = study["factors"]
    lines = [
        f"# CSI 300 cross-sectional factor lab ({date.today():%Y-%m-%d})",
        "",
        "A read-only research track. It does not change the counted strategy, the frozen "
        "policy, the paper account or any evidence file.",
        "",
        "## Setup",
        "",
        f"- Panel: {study['calendar']['first']} to {study['calendar']['last']}, "
        f"{study['calendar']['sessions']} sessions, point-in-time CSI 300 membership "
        f"({inputs['member_cells']:,} member-days).",
        f"- Training/selection: signals through {study['split']['train_end']}, purged so the "
        f"T+1+h exit open is on or before that date ({study['split']['train_signal_dates'][h]} "
        f"signal dates at h={h}).",
        f"- Locked hold-out: {study['split']['holdout_start']} to the last date "
        f"({study['split']['holdout_signal_dates']} signal dates). Nothing was tuned on it.",
        "- Forward return: the signal at the T close earns hfq `open[T+1+h] / open[T+1] - 1`. "
        "Suspended entry or exit days are dropped; limit-up entries are not filtered.",
        f"- Preprocessing per date: {study['settings']['winsorize']}, z-score, "
        f"{study['settings']['neutralize']}, z-score again.",
        f"- Missing inputs: {inputs['member_cells_missing_market_cap']:,} member-days lack a "
        f"market cap ({', '.join(inputs['symbols_without_market_cap']) or 'none'} have Baidu-only "
        f"valuations) and {inputs['member_cells_unclassified_industry']:,} lack an industry; "
        "those cells are excluded, not imputed.",
        f"- Primary horizon h={h} sessions. All Rank IC t-stats divide the overlapping series "
        "by sqrt(h) (`t = ICIR * sqrt(n / h)`).",
        "",
        "## Multiple testing",
        "",
        f"{mt['factors_tested']} factors x {mt['horizons_tested']} horizons = {mt['tests']} "
        f"tests. By chance about {mt['expected_abs_t_above_2_by_chance']} would show |t| > 2; "
        f"in training {mt['train_abs_t_above_2']} did. The Bonferroni 5% threshold is "
        f"|t| > {mt['bonferroni_t_threshold_5pct']:.2f}; {mt['train_abs_t_above_bonferroni']} "
        f"passed it in training. {mt['primary_horizon_sign_kept_in_holdout']} of "
        f"{mt['factors_tested']} factors kept the sign of their h={h} Rank IC in the hold-out.",
        "",
        f"## Factors (h={h}, neutralized)",
        "",
        "| Factor | Category | Train Rank IC | Train ICIR | Train t | Hold-out Rank IC "
        "| Hold-out ICIR | Hold-out t | Hold-out Q5-Q1 ann. | Monotonicity | AC(1) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    order = sorted(factors, key=lambda n: -(factors[n]["train"]["rank_ic"][h]["icir"] or -9))
    for name in order:
        e = factors[name]
        tr, ho = e["train"]["rank_ic"][h], e["holdout"]["rank_ic"][h]
        q = e["holdout"]["quantiles"][h]
        lines.append(
            f"| `{name}` | {e['category']} | {_f(tr['mean'], 4)} | {_f(tr['icir'], 2)} "
            f"| {_f(tr['t_stat_nonoverlap'], 2)} | {_f(ho['mean'], 4)} | {_f(ho['icir'], 2)} "
            f"| {_f(ho['t_stat_nonoverlap'], 2)} | {_f(q.get('long_short_annualized'), 3, True)} "
            f"| {_f(q.get('monotonicity'), 2)} | {_f(e['train']['autocorrelation']['1'], 2)} |"
        )
    lines += [
        "",
        "Q5-Q1 uses equal-weight quintiles rebalanced every h sessions on non-overlapping "
        "periods, before costs. Train Rank IC for h=1 and h=20, IC decay, Pearson IC, "
        "quintile turnover and the full correlation matrix are in the JSON.",
        "",
        "## IC decay (training, mean Rank IC vs the one-day return k sessions ahead)",
        "",
        "| Factor | k=1 | k=2 | k=3 | k=5 | k=10 | k=20 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in order[:8]:
        d = factors[name]["train"]["ic_decay"]
        lines.append(f"| `{name}` | " + " | ".join(_f(d[k], 4) for k in ("1", "2", "3", "5", "10", "20")) + " |")
    lines += ["", "## Highly correlated pairs (training, |mean Spearman| > 0.7)", ""]
    corr = study["correlation_train"]
    names = list(corr)
    pairs = [(a, b, corr[a][b]) for i, a in enumerate(names) for b in names[i + 1:]
             if corr[a][b] is not None and abs(corr[a][b]) > 0.7]
    lines += [f"- `{a}` / `{b}`: {c:.2f}" for a, b, c in sorted(pairs, key=lambda p: -abs(p[2]))] or ["- none"]
    lines += ["", "## Combined signals (hold-out)", "",
              "| Signal | Hold-out Rank IC h=1 | h=5 | h=20 | Hold-out ICIR h=5 | Hold-out t h=5 "
              "| Pearson IC h=5 | Q5-Q1 ann. h=5 | Q5-Q1 Sharpe h=5 | Top-quintile turnover h=5 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    rows = [(label, combo["holdout"]) for label, combo in study["combined"].items()]
    rows += [(f"{label}, ex {combo['holdout_ex_window']['window'][0]}..{combo['holdout_ex_window']['window'][1]}",
              combo["holdout_ex_window"])
             for label, combo in study["combined"].items() if "holdout_ex_window" in combo]
    for label, ho in rows:
        q = ho["quantiles"]["5"]
        lines.append(
            f"| {label} | {_f(ho['rank_ic']['1']['mean'], 4)} | {_f(ho['rank_ic']['5']['mean'], 4)} "
            f"| {_f(ho['rank_ic']['20']['mean'], 4)} | {_f(ho['rank_ic']['5']['icir'], 2)} "
            f"| {_f(ho['rank_ic']['5']['t_stat_nonoverlap'], 2)} | {_f(ho['ic']['5']['mean'], 4)} "
            f"| {_f(q.get('long_short_annualized'), 3, True)} | {_f(q.get('long_short_sharpe'), 2)} "
            f"| {_f(q.get('top_quantile_turnover'), 3, True)} |"
        )
    ew = study["combined"].get("equal_weight")
    ridge = study["combined"]["ridge"]
    lines += [
        "",
        f"- Equal weight: mean of the {len(ew['factors']) if ew else 0} neutralized factors with "
        f"positive training Rank ICIR at h={h}, re-standardized per date: "
        f"{', '.join(f'`{n}`' for n in ew['factors']) if ew else 'none'}. "
        + (f"Its in-sample training Rank IC (h={h}) is "
           f"{_f(ew['train']['rank_ic'][h]['mean'], 4)}, for reference only." if ew else ""),
        f"- Ridge: all {len(FACTORS)} neutralized factors, fixed penalty "
        f"{ridge['penalty']} (not tuned), target = {ridge['target']}. Expanding window, refit on "
        + ", ".join(f"{f['refit_date']} ({f['train_rows']:,} rows, last signal "
                    f"{f['train_last_signal_date']})" for f in ridge["fits"])
        + "; each fit uses only returns whose exit open is before its refit date.",
        "",
        "## Reading the results",
        "",
        "- These are gross, equal-weight, daily-data statistics on 300 large caps. They are a "
        "screen for which factors deserve a costed backtest, not evidence of tradable profit.",
        "- Rank IC measures ordering; Pearson IC and quintile means are dominated by extreme "
        "returns. When they disagree (positive Rank IC, flat Pearson IC, negative Q5-Q1), a few "
        "large winners in the bottom quintile outweigh a correct ordering of the typical stock.",
        "- Hold-out numbers are the only out-of-sample evidence here; training columns were "
        "used for selection and are optimistic by construction.",
        "- Industry labels are the current CNInfo Shenwan history; a symbol whose first record "
        "is after a date takes its earliest label (minor classification look-ahead).",
        "",
        f"JSON: `{json_path}` (gitignored). Rerun: `.venv/bin/python scripts/run_factor_lab.py`.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
