"""Scoring v2 (rank composite) study next to the counted 35/25/25/15 score.

Read-only research track. It reuses the factor lab's panel and preprocessing,
fits signs and category weights on training dates only, evaluates the frozen
composite once on the hold-out, recomputes the counted score on the same dates
for a side-by-side, and writes the latest-date v2 scores for the picker. The
counted strategy, frozen policy and evidence files are never modified.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (SRC, ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from run_factor_lab import MAIN, _f, _git_sha, _json_default, input_refs, load_panel  # noqa: E402

from fintech_quant.data.historical_universe import load_membership_intervals  # noqa: E402
from fintech_quant.execution.paper_evidence import approved_paper_policy  # noqa: E402
from fintech_quant.research.dataset import load_research_dataset  # noqa: E402
from fintech_quant.research.factor_lab import daily_ic, ic_summary  # noqa: E402
from fintech_quant.research.scoring import build_stock_scores  # noqa: E402
from fintech_quant.research.scoring_v2 import (  # noqa: E402
    CATEGORIES,
    PRIMARY_HORIZON,
    current_score_summary,
    run_scoring_v2_study,
)

COMPONENTS = ("fundamental", "technical", "capital_flow", "sentiment")
RESEARCH_LABEL = "研究评分 v2（横截面排名合成），不驱动计数策略"


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
    parser.add_argument("--stress-window", nargs=2, default=["2024-09-15", "2024-10-31"])
    parser.add_argument("--output-dir", default=str(MAIN / "outputs/research/scoring_v2"))
    parser.add_argument("--report",
                        default=str(ROOT / f"docs/research/{date.today():%Y-%m-%d}-scoring-v2.md"))
    args = parser.parse_args()

    state_path, industry_cache = Path(args.pipeline_state), Path(args.industry_cache)
    inputs = load_panel(state_path, industry_cache, args.offline)
    universe = inputs["universe"]
    study, result, forwards, split_dates = run_scoring_v2_study(
        inputs["panel"], universe, inputs["industry"], inputs["log_mcap"],
        args.train_end, args.holdout_start, tuple(args.stress_window))
    study["inputs"] = input_refs(inputs, state_path, industry_cache)

    total, confidence, components = current_scores(inputs, universe)
    common = result.score.notna() & total.notna()
    policy = approved_paper_policy()
    study["current_score"] = {
        "cells": "member-days scored by both v2 and the counted score",
        "buy_threshold": policy["buy_threshold"],
        "confidence_gate": policy["minimum_score_confidence"],
        **current_score_summary(
            total.where(common), confidence.where(common),
            {name: frame.where(common) for name, frame in components.items()},
            forwards, split_dates, float(policy["buy_threshold"]),
            float(policy["minimum_score_confidence"])),
        "rank_correlation_with_v2": {
            split: float(daily_ic(result.composite.where(common).loc[d[1]],
                                  total.where(common).loc[d[1]]).mean())
            for split, d in split_dates.items()
        },
    }
    study["v2_rank_ic_same_cells"] = {
        split: {str(h): ic_summary(daily_ic(result.composite.where(common).loc[d[h]],
                                            forwards[h].loc[d[h]]), h) for h in (5, 20)}
        for split, d in split_dates.items()
    }

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    study_path = out_dir / "scoring_v2.json"
    study_path.write_text(json.dumps(study, ensure_ascii=False, indent=2, default=_json_default)
                          + "\n", encoding="utf-8")
    latest_path = out_dir / "latest_scores.json"
    latest_path.write_text(json.dumps(latest_snapshot(study, result, universe), ensure_ascii=False,
                                      indent=2, default=_json_default) + "\n", encoding="utf-8")
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(study, study_path), encoding="utf-8")
    print(f"wrote {study_path}\nwrote {latest_path}\nwrote {report}")
    return 0


def current_scores(inputs: dict, universe: pd.DataFrame):
    """The counted score recomputed with the paper path's loader (no information records)."""
    factor_dir = Path(inputs["factor_manifest"]).parent
    membership = Path(inputs["membership_path"])
    with tempfile.TemporaryDirectory(prefix="scoring-v2-") as tmp:
        universe_csv = Path(tmp) / "universe.csv"
        symbols = sorted({i.symbol for i in load_membership_intervals(membership)})
        with universe_csv.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=("symbol", "name", "sector"))
            writer.writeheader()
            writer.writerows({"symbol": s, "name": "", "sector": ""} for s in symbols)
        dataset = load_research_dataset(
            Path(inputs["signal_manifest"]).parent / "features.csv",
            universe_csv,
            fundamentals_path=factor_dir / "fundamentals.csv",
            capital_flow_path=factor_dir / "capital_flow.csv",
            membership_path=membership,
            require_point_in_time=True,
        )
    scores = build_stock_scores(dataset)
    records = [
        {"date": day.isoformat(), "symbol": symbol, "total": s.total, "confidence": s.confidence,
         **{name: s.components[name].score for name in COMPONENTS}}
        for (day, symbol), s in scores.items()
    ]
    frame = pd.DataFrame.from_records(records)

    def wide(column: str) -> pd.DataFrame:
        return (frame.pivot(index="date", columns="symbol", values=column)
                .reindex(index=universe.index, columns=universe.columns).where(universe))

    return wide("total"), wide("confidence"), {name: wide(name) for name in COMPONENTS}


def latest_snapshot(study: dict, result, universe: pd.DataFrame) -> dict[str, object]:
    day = universe.index[-1]
    scored = result.score.loc[day].dropna()
    category_pct = {c: z.loc[day, scored.index].rank(pct=True) * 100.0
                    for c, z in result.categories.items()}
    weights = study["fit"]["weights"]
    rows = {}
    for symbol in scored.index:
        rows[symbol] = {
            "score": round(float(scored[symbol]), 2),
            "coverage": round(float(result.coverage.loc[day, symbol]), 4),
            "composite": round(float(result.composite.loc[day, symbol]), 4),
            "categories": {
                c: {
                    "z": round(float(result.categories[c].loc[day, symbol]), 4),
                    "percentile": round(float(category_pct[c][symbol]), 1),
                    "weight": round(float(weights[c]), 4),
                }
                for c in CATEGORIES
            },
        }
    members = universe.columns[universe.loc[day].to_numpy()]
    return {
        "as_of": day,
        "label": RESEARCH_LABEL,
        "counted": False,
        "train_window": [study["fit"]["train_first"], study["fit"]["train_last"]],
        "weights": weights,
        "signs": study["fit"]["signs"],
        "git_sha": _git_sha(),
        "members": int(len(members)),
        "unscored_members": sorted(set(members) - set(scored.index)),
        "scores": rows,
    }


# ------------------------------------------------------------------------- report

CATEGORY_LABELS = {"value": "value", "quality_growth": "quality/growth", "low_risk": "low risk",
                   "liquidity": "liquidity", "reversal": "reversal", "momentum": "momentum 12-1"}


def _ic_row(label: str, block: dict) -> str:
    cells = []
    for h in ("5", "20"):
        s = block[h]
        cells += [_f(s["mean"], 4), _f(s["icir"], 2), _f(s["t_stat_nonoverlap"], 2)]
    return f"| {label} | " + " | ".join(cells) + " |"


def render_report(study: dict, json_path: Path) -> str:
    fit = study["fit"]
    comp = study["composite"]
    cur = study["current_score"]
    split = study["split"]
    window = "..".join(split["stress_window"])
    h = str(PRIMARY_HORIZON)
    lines = [
        f"# Scoring v2: rank-based composite multi-factor score ({date.today():%Y-%m-%d})",
        "",
        "A research track. It does not change the counted strategy's score "
        "(`features/factors.py`, `research/scoring.py`), the frozen policy, the paper account "
        "or any evidence file, and it does not drive any target.",
        "",
        "## Predeclared design",
        "",
        "The design is fixed in the docstring of `src/fintech_quant/research/scoring_v2.py`, "
        "committed before the first hold-out run. In short:",
        "",
        "- Inputs: the factor lab's neutralized factor z-scores (MAD winsorize, z-score, OLS "
        "residual on Shenwan level-1 dummies plus log market cap, z-score again).",
        "- Categories: " + "; ".join(
            f"{CATEGORY_LABELS[c]}: " + ", ".join(f"`{n}`" for n in names)
            for c, names in study["design"]["categories"].items()) + ".",
        f"- Each factor's sign is the sign of its training Rank ICIR at h={h}; a category is the "
        "equal-weight mean of its sign-aligned factors (a missing factor counts as 0), scaled "
        "to unit cross-sectional standard deviation.",
        f"- Category weights are proportional to each category's training Rank ICIR at h={h}, "
        "clipped at 0 and normalized.",
        "- Missing inputs are a neutral 0 and lower a coverage score (available factors / 9); "
        "they never cost points. A stock with coverage 0 is not scored.",
        "- The final score is the cross-sectional percentile of the weighted composite, in "
        "(0, 100].",
        f"- Variants evaluated on the hold-out: {study['design']['variants_evaluated_on_holdout']}. "
        "No parameter was changed after the hold-out was seen.",
        "",
        "## Fit (training only)",
        "",
        f"Training signal dates {fit['train_first']} to {fit['train_last']} "
        f"({fit['train_dates']} dates at h={h}, purged so the T+1+h exit open is on or before "
        f"{split['train_end']}).",
        "",
        "| Category | Factor | Expected sign | Training Rank ICIR h=5 | Sign used | "
        "Category training ICIR | Weight |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for c, names in study["design"]["categories"].items():
        for i, n in enumerate(names):
            first = i == 0
            lines.append(
                f"| {CATEGORY_LABELS[c] if first else ''} | `{n}` "
                f"| {study['design']['expected_signs'][n]:+d} | {_f(fit['factor_train_icir'][n], 3)} "
                f"| {fit['signs'][n]:+d} "
                f"| {_f(fit['category_train_icir'][c], 3) if first else ''} "
                f"| {_f(fit['weights'][c], 3) if first else ''} |")
    disagree = study["sign_disagreements"]
    lines += [
        "",
        ("Training signs that disagree with the expected sign: "
         + ", ".join(f"`{n}`" for n in disagree) + ". The rule uses the training sign."
         if disagree else "Every training sign matches the expected sign."),
        "",
        f"Coverage: {study['coverage']['scored_cells']:,} of "
        f"{study['coverage']['member_cells']:,} member-days are scored; mean coverage of a "
        f"scored stock is {_f(study['coverage']['mean_coverage_scored'], 3, True)}. Per factor: "
        + ", ".join(f"`{n}` {_f(v, 3, True)}"
                    for n, v in study["coverage"]["factor_coverage"].items()) + ".",
        "",
        "## Composite: Rank IC",
        "",
        "| Split | Rank IC h=5 | ICIR h=5 | t h=5 | Rank IC h=20 | ICIR h=20 | t h=20 |",
        "|---|---:|---:|---:|---:|---:|---:|",
        _ic_row("training (in-sample: signs and weights fit here)", comp["train"]["rank_ic"]),
        _ic_row("hold-out", comp["holdout"]["rank_ic"]),
        _ic_row(f"hold-out ex {window}", comp["holdout_ex_window"]["rank_ic"]),
        "",
        "t divides the overlapping daily series by sqrt(h): `t = ICIR * sqrt(n / h)`. "
        "Pearson IC (h=5 / h=20): " + "; ".join(
            f"{label} {_f(comp[key]['ic']['5']['mean'], 4)} / {_f(comp[key]['ic']['20']['mean'], 4)}"
            for label, key in (("training", "train"), ("hold-out", "holdout"),
                               ("hold-out ex window", "holdout_ex_window"))) + ".",
        "",
        "## Composite: quintiles (equal weight, non-overlapping, before costs)",
        "",
        "| Split | h | Q1 ann. | Q2 | Q3 | Q4 | Q5 ann. | Q5-Q1 ann. | Q5-Q1 Sharpe "
        "| Monotonicity | Top-quintile turnover |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, key in (("training", "train"), ("hold-out", "holdout"),
                       (f"hold-out ex {window}", "holdout_ex_window")):
        for hz in ("5", "20"):
            q = comp[key]["quantiles"][hz]
            r = q.get("annualized_quantile_return", {})
            lines.append(
                f"| {label} | {hz} | " + " | ".join(_f(r.get(str(i)), 3, True) for i in range(1, 6))
                + f" | {_f(q.get('long_short_annualized'), 3, True)} "
                f"| {_f(q.get('long_short_sharpe'), 2)} | {_f(q.get('monotonicity'), 2)} "
                f"| {_f(q.get('top_quantile_turnover'), 3, True)} |")
    lines += [
        "",
        "Top-quintile turnover is the mean share of the top quintile replaced at each h-session "
        "rebalance.",
        "",
        "## Categories: Rank IC h=5 (hold-out uses the frozen training signs)",
        "",
        "| Category | Weight | Training | Hold-out | Hold-out t | Hold-out ex window |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for c, block in study["categories"].items():
        lines.append(
            f"| {CATEGORY_LABELS[c]} | {_f(fit['weights'][c], 3)} "
            f"| {_f(block['train'][h]['mean'], 4)} | {_f(block['holdout'][h]['mean'], 4)} "
            f"| {_f(block['holdout'][h]['t_stat_nonoverlap'], 2)} "
            f"| {_f(block['holdout_ex_window'][h]['mean'], 4)} |")
    same = study["v2_rank_ic_same_cells"]
    lines += [
        "",
        "## Side by side with the counted 35/25/25/15 score",
        "",
        f"The counted score is recomputed with the paper path's loader and `score_stock` on "
        f"every member-day (no information records, as in the daily cycle). Both scores are "
        f"compared on the {cur['scored_cells']:,} member-days that both score.",
        "",
        "| Score | Split | Rank IC h=5 | ICIR h=5 | t h=5 | Rank IC h=20 | ICIR h=20 | t h=20 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, key in (("training", "train"), ("hold-out", "holdout"),
                       (f"hold-out ex {window}", "holdout_ex_window")):
        lines.append(_ic_row(f"counted total | {label}", cur["rank_ic"][key]))
        lines.append(_ic_row(f"v2 composite | {label}", same[key]))
    conf = ", ".join(f"{k}: {_f(v, 3, True)}" for k, v in cur["confidence_distribution"].items())
    lines += [
        "",
        f"- Distinct values of the counted total: {cur['distinct_totals']} over all member-days, "
        f"median {cur['distinct_totals_per_date_median']:.0f} per date; maximum observed "
        f"{cur['max_total']:.2f} of 100.",
        "- Distinct values per component (share of member-days at the most common value): "
        + ", ".join(f"{n} {cur['distinct_component_values'][n]} "
                    f"({_f(cur['component_mode_share'][n], 3, True)})"
                    for n in COMPONENTS) + ".",
        f"- Confidence values: {conf}.",
        f"- Share of member-days below the {cur['confidence_gate']} confidence gate: "
        f"{_f(cur['share_below_confidence_gate'], 3, True)}. Share at or above the "
        f"{cur['buy_threshold']:.0f}-point threshold: "
        f"{_f(cur['share_at_or_above_threshold'], 3, True)}; of those, the gate blocks "
        f"{_f(cur['share_above_threshold_blocked_by_gate'], 3, True)}.",
        "- Mean cross-sectional Spearman between the v2 composite and the counted total: "
        + ", ".join(f"{k} {_f(v, 3)}" for k, v in cur["rank_correlation_with_v2"].items()) + ".",
        "",
        "## Reading the results",
        "",
        "- These are gross, equal-weight, daily-data statistics on 300 large caps; they do not "
        "include costs, limit-up/down fills or capacity and are not evidence of tradable profit.",
        "- Training numbers are in-sample by construction. The hold-out is the only "
        "out-of-sample evidence, and it was evaluated once.",
        "- The nine factors were specified after the factor-lab report, which displayed "
        "hold-out statistics for all 27 factors, so the factor list is not fully blind to the "
        "hold-out even though signs and weights are fit on training dates only.",
        "- The v2 score is shown in the picker as a research score. It does not drive the "
        "counted strategy, which stays frozen until its evidence window completes.",
        "",
        f"JSON: `{json_path}` (gitignored). Rerun: "
        "`.venv/bin/python scripts/run_scoring_v2.py --offline`.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
