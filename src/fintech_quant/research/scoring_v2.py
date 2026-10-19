"""Scoring v2: a rank-based composite multi-factor score (research track).

This module does not drive the counted paper strategy. The counted score
(``features/factors.py`` and ``research/scoring.py``) is frozen for the
paper-evidence window; v2 only reads the processed panels and writes research
outputs.

Predeclared design (fixed before any hold-out evaluation)
---------------------------------------------------------
Inputs are the factor lab's neutralized factor z-scores
(``factor_lab.preprocess_factors``: per date MAD winsorize, z-score, OLS
residual on Shenwan level-1 dummies plus z-scored log market cap, z-score
again, point-in-time CSI 300 members only).

1. Categories and factors (the expected sign is in brackets):

   ============== ===============================================
   value          ``ep`` (+), ``bp`` (+)
   quality_growth ``roe`` (+), ``growth`` (+)
   low_risk       ``vol_60d`` (-), ``max_ret_20d`` (-)
   liquidity      ``turnover_20d`` (-)
   reversal       ``rev_5d`` (+)
   momentum       ``mom_12m_skip1m`` (+), i.e. 12-1 momentum
   ============== ===============================================

2. Sign alignment: each factor is multiplied by the sign of its training-period
   Rank ICIR at the primary horizon (h=5). The expected signs above are not
   used; when the training sign disagrees, the training sign wins and the
   report says so.
3. Category z-score: the equal-weight average of the sign-aligned factor
   z-scores, divided by the number of factors in the category (a missing factor
   contributes 0), then divided by its cross-sectional standard deviation over
   the date's scored stocks. The factor inputs are already mean-zero per date,
   so no re-centering is applied and a stock with no input stays exactly 0.
4. Category weights: proportional to each category z-score's training-period
   Rank ICIR at h=5, clipped at 0 and normalized to sum to 1.
5. Missing inputs: a missing factor is a neutral 0 z-score; it does not cost
   points. Each stock gets a coverage score = available factors / 9. A stock
   with no available factor (coverage 0) is not scored.
6. Composite = sum of weight x category z-score. The final score is the
   composite's cross-sectional percentile among the date's scored stocks,
   ``rank(pct=True) * 100``, so it lies in (0, 100].
7. Training = signal dates through 2024-06-30, purged so the T+1+h exit open is
   on or before that date. The hold-out (from 2024-07-01) is evaluated once with
   the fit frozen. Exactly one composite variant is evaluated on the hold-out.

The fit (signs and weights) uses only training dates. A score on date T uses
only the T cross section of factors that themselves use data known at the T
close, so it never depends on later prices or fundamentals.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from fintech_quant.research.factor_lab import (
    FACTORS,
    daily_ic,
    evaluate_signal,
    forward_open_returns,
    ic_summary,
    preprocess_factors,
    purged_train_dates,
)

CATEGORIES: dict[str, tuple[str, ...]] = {
    "value": ("ep", "bp"),
    "quality_growth": ("roe", "growth"),
    "low_risk": ("vol_60d", "max_ret_20d"),
    "liquidity": ("turnover_20d",),
    "reversal": ("rev_5d",),
    "momentum": ("mom_12m_skip1m",),
}
EXPECTED_SIGNS: dict[str, int] = {
    "ep": 1, "bp": 1, "roe": 1, "growth": 1, "vol_60d": -1, "max_ret_20d": -1,
    "turnover_20d": -1, "rev_5d": 1, "mom_12m_skip1m": 1,
}
FACTOR_NAMES: tuple[str, ...] = tuple(n for names in CATEGORIES.values() for n in names)
PRIMARY_HORIZON = 5
VARIANTS_EVALUATED_ON_HOLDOUT = 1


@dataclass(frozen=True)
class ScoringV2Fit:
    horizon: int
    train_first: str
    train_last: str
    train_dates: int
    factor_train_icir: dict[str, float | None]
    signs: dict[str, int]
    category_train_icir: dict[str, float | None]
    weights: dict[str, float]

    def to_json(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ScoringV2Result:
    score: pd.DataFrame          # percentile (0, 100], NaN when not scored
    composite: pd.DataFrame      # weighted category z-scores, NaN when not scored
    categories: dict[str, pd.DataFrame]
    coverage: pd.DataFrame       # available factors / 9


def _sign(value: float | None) -> int:
    if value is None or not np.isfinite(value) or value == 0:
        return 0
    return 1 if value > 0 else -1


def coverage(factors: dict[str, pd.DataFrame]) -> pd.DataFrame:
    present = sum(factors[n].notna().astype(float) for n in FACTOR_NAMES)
    return present / len(FACTOR_NAMES)


def category_scores(
    factors: dict[str, pd.DataFrame], signs: dict[str, int]
) -> dict[str, pd.DataFrame]:
    """Per-category z-scores over scored stocks; a missing factor counts as 0."""
    scored = coverage(factors) > 0
    out = {}
    for category, names in CATEGORIES.items():
        raw = sum(signs[n] * factors[n].fillna(0.0) for n in names) / len(names)
        raw = raw.where(scored)
        z = raw.div(raw.std(axis=1, ddof=0).replace(0, np.nan), axis=0)
        out[category] = z.fillna(0.0).where(scored)
    return out


def category_weights(category_icir: dict[str, float | None]) -> dict[str, float]:
    clipped = {c: max(v, 0.0) if v is not None and np.isfinite(v) else 0.0
               for c, v in category_icir.items()}
    total = sum(clipped.values())
    if total <= 0:
        raise ValueError("no category has a positive training ICIR")
    return {c: v / total for c, v in clipped.items()}


def _train_icir(signal: pd.DataFrame, forward: pd.DataFrame, dates: pd.Index,
                horizon: int) -> float | None:
    return ic_summary(daily_ic(signal.loc[dates], forward.loc[dates]), horizon)["icir"]


def fit_scoring_v2(
    factors: dict[str, pd.DataFrame],
    forward: pd.DataFrame,
    train_dates: pd.Index,
    horizon: int = PRIMARY_HORIZON,
) -> ScoringV2Fit:
    """Signs and category weights from training dates only."""
    factor_icir = {n: _train_icir(factors[n], forward, train_dates, horizon) for n in FACTOR_NAMES}
    signs = {n: _sign(v) for n, v in factor_icir.items()}
    categories = category_scores(factors, signs)
    category_icir = {c: _train_icir(z, forward, train_dates, horizon)
                     for c, z in categories.items()}
    return ScoringV2Fit(
        horizon=horizon,
        train_first=str(train_dates[0]),
        train_last=str(train_dates[-1]),
        train_dates=int(len(train_dates)),
        factor_train_icir=factor_icir,
        signs=signs,
        category_train_icir=category_icir,
        weights=category_weights(category_icir),
    )


def score_scoring_v2(factors: dict[str, pd.DataFrame], fit: ScoringV2Fit) -> ScoringV2Result:
    categories = category_scores(factors, fit.signs)
    composite = sum(fit.weights[c] * z for c, z in categories.items())
    return ScoringV2Result(
        score=composite.rank(axis=1, pct=True) * 100.0,
        composite=composite,
        categories=categories,
        coverage=coverage(factors),
    )


def snapshot_view(
    snapshot: Mapping[str, object] | None, symbol: str, as_of: str
) -> dict[str, object] | None:
    """One stock's research score from a ``latest_scores.json`` snapshot, for display only."""
    if not snapshot:
        return None
    row = dict(snapshot.get("scores") or {}).get(symbol)  # type: ignore[arg-type]
    return {
        "label": snapshot.get("label"),
        "as_of": snapshot.get("as_of"),
        "stale": snapshot.get("as_of") != as_of,
        "counted": False,
        "score": None if row is None else row["score"],
        "coverage": None if row is None else row["coverage"],
        "categories": None if row is None else row["categories"],
        "inverted": sorted(
            name for name, sign in dict(snapshot.get("signs") or {}).items() if sign < 0  # type: ignore[arg-type]
        ),
    }


# ------------------------------------------------------------------ evaluation


def current_score_summary(
    total: pd.DataFrame,
    confidence: pd.DataFrame,
    components: dict[str, pd.DataFrame],
    forwards: dict[int, pd.DataFrame],
    split_dates: dict[str, dict[int, pd.Index]],
    buy_threshold: float,
    confidence_gate: float,
    horizons: tuple[int, ...] = (5, 20),
) -> dict[str, object]:
    """Rank IC, value spread and gate behaviour of the counted 35/25/25/15 total."""
    rank_ic = {
        split: {str(h): ic_summary(daily_ic(total.loc[d[h]], forwards[h].loc[d[h]]), h)
                for h in horizons}
        for split, d in split_dates.items()
    }
    cells = total.notna()
    values = total.to_numpy()[cells.to_numpy()]
    conf = confidence.to_numpy()[cells.to_numpy()]
    above = values >= buy_threshold
    per_date = total.nunique(axis=1)[cells.any(axis=1)]
    return {
        "scored_cells": int(cells.to_numpy().sum()),
        "rank_ic": rank_ic,
        "distinct_totals": int(len(np.unique(values))),
        "distinct_totals_per_date_median": float(per_date.median()),
        "max_total": float(values.max()),
        "distinct_component_values": {
            name: int(len(np.unique(frame.to_numpy()[cells.to_numpy()])))
            for name, frame in components.items()
        },
        "component_mode_share": {
            name: float(pd.Series(frame.to_numpy()[cells.to_numpy()]).value_counts(normalize=True)
                        .iloc[0])
            for name, frame in components.items()
        },
        "confidence_distribution": {
            str(k): float(v)
            for k, v in pd.Series(conf).round(4).value_counts(normalize=True).head(6).items()
        },
        "share_below_confidence_gate": float((conf < confidence_gate).mean()),
        "share_at_or_above_threshold": float(above.mean()),
        "share_above_threshold_blocked_by_gate": (
            float((conf[above] < confidence_gate).mean()) if above.any() else None
        ),
    }


def run_scoring_v2_study(
    panel: dict[str, pd.DataFrame],
    universe: pd.DataFrame,
    industry: pd.DataFrame,
    log_mcap: pd.DataFrame,
    train_end: str,
    holdout_start: str,
    stress_window: tuple[str, str],
    horizons: tuple[int, ...] = (5, 20),
) -> tuple[dict[str, object], ScoringV2Result, dict[int, pd.DataFrame], dict]:
    """Fit on training dates, evaluate the frozen composite on the hold-out."""
    calendar = universe.index
    definitions = {f.name: f for f in FACTORS}
    raw = {n: definitions[n].compute(panel).astype(float) for n in FACTOR_NAMES}
    factors = preprocess_factors(raw, industry, log_mcap, universe)
    forwards = {h: forward_open_returns(panel["open"].reindex_like(universe), h)
                for h in sorted(set(horizons) | {1, 20})}
    holdout = calendar[calendar >= holdout_start]
    kept = holdout[(holdout < stress_window[0]) | (holdout > stress_window[1])]
    split_dates = {
        "train": {h: purged_train_dates(calendar, train_end, h) for h in forwards},
        "holdout": {h: holdout for h in forwards},
        "holdout_ex_window": {h: kept for h in forwards},
    }
    fit = fit_scoring_v2(factors, forwards[PRIMARY_HORIZON], split_dates["train"][PRIMARY_HORIZON])
    result = score_scoring_v2(factors, fit)
    evaluation = evaluate_signal(result.composite, forwards, split_dates)
    category_ic = {
        category: {
            split: {str(h): ic_summary(daily_ic(z.loc[d[h]], forwards[h].loc[d[h]]), h)
                    for h in horizons}
            for split, d in split_dates.items()
        }
        for category, z in result.categories.items()
    }
    members = universe.to_numpy()
    study = {
        "design": {
            "categories": {c: list(n) for c, n in CATEGORIES.items()},
            "expected_signs": EXPECTED_SIGNS,
            "primary_horizon": PRIMARY_HORIZON,
            "variants_evaluated_on_holdout": VARIANTS_EVALUATED_ON_HOLDOUT,
        },
        "calendar": {"first": calendar[0], "last": calendar[-1], "sessions": len(calendar)},
        "split": {
            "train_end": train_end,
            "holdout_start": holdout_start,
            "stress_window": list(stress_window),
            "signal_dates": {split: {str(h): len(d) for h, d in by.items()}
                             for split, by in split_dates.items()},
        },
        "fit": fit.to_json(),
        "sign_disagreements": [n for n in FACTOR_NAMES if fit.signs[n] != EXPECTED_SIGNS[n]],
        "coverage": {
            "member_cells": int(members.sum()),
            "scored_cells": int(result.score.notna().to_numpy().sum()),
            "mean_coverage_scored": float(np.nanmean(
                result.coverage.where(result.score.notna()).to_numpy())),
            "factor_coverage": {n: float((factors[n].notna().to_numpy() & members).sum()
                                         / members.sum()) for n in FACTOR_NAMES},
        },
        "composite": evaluation,
        "categories": category_ic,
    }
    return study, result, forwards, split_dates
