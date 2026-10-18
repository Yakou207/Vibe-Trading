"""Cross-sectional factor research on the CSI 300 point-in-time panel.

This is a research track that sits beside the counted strategy. It reads the
processed panels, never writes to them, and is not used by the paper account.

Conventions
-----------
* Every panel is a wide ``DataFrame``: index = trading dates (ISO strings,
  sorted), columns = symbols. A missing row (suspension) is NaN.
* A factor value on date T uses only data known at the T close.
* The forward return paired with the T value is earned by buying at the T+1
  open and selling at the T+1+h open (adjusted prices), so a signal formed at
  the close can actually be traded.
* Cross sections are restricted to point-in-time index members on T.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from statistics import NormalDist
from typing import Callable

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252
MONTH = 21
MAD_SCALE = 1.4826


# --------------------------------------------------------------------------- factors


@dataclass(frozen=True)
class FactorDefinition:
    name: str
    category: str
    formula: str
    compute: Callable[[dict[str, pd.DataFrame]], pd.DataFrame]


def _returns(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return panel["close"].pct_change(fill_method=None)


def _window_return(close: pd.DataFrame, recent: int, far: int) -> pd.DataFrame:
    return close.shift(recent) / close.shift(far) - 1.0


def _safe_inverse(frame: pd.DataFrame) -> pd.DataFrame:
    return (1.0 / frame).replace([np.inf, -np.inf], np.nan)


def _turnover(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return (panel["amount"] / panel["float_mcap"]).replace([np.inf, -np.inf], np.nan)


FACTORS: list[FactorDefinition] = [
    # momentum: all windows skip the most recent month (21 sessions)
    FactorDefinition("mom_1m_skip1m", "momentum", "close[T-21] / close[T-42] - 1",
                     lambda p: _window_return(p["close"], MONTH, 2 * MONTH)),
    FactorDefinition("mom_3m_skip1m", "momentum", "close[T-21] / close[T-63] - 1",
                     lambda p: _window_return(p["close"], MONTH, 3 * MONTH)),
    FactorDefinition("mom_6m_skip1m", "momentum", "close[T-21] / close[T-126] - 1",
                     lambda p: _window_return(p["close"], MONTH, 6 * MONTH)),
    FactorDefinition("mom_12m_skip1m", "momentum", "close[T-21] / close[T-252] - 1",
                     lambda p: _window_return(p["close"], MONTH, 12 * MONTH)),
    # reversal
    FactorDefinition("rev_5d", "reversal", "-(close[T] / close[T-5] - 1)",
                     lambda p: -_window_return(p["close"], 0, 5)),
    FactorDefinition("rev_20d", "reversal", "-(close[T] / close[T-20] - 1)",
                     lambda p: -_window_return(p["close"], 0, 20)),
    # volatility
    FactorDefinition("vol_20d", "volatility", "std(daily return, 20)",
                     lambda p: _returns(p).rolling(20, min_periods=15).std()),
    FactorDefinition("vol_60d", "volatility", "std(daily return, 60)",
                     lambda p: _returns(p).rolling(60, min_periods=45).std()),
    FactorDefinition("max_ret_20d", "volatility", "max(daily return, 20)",
                     lambda p: _returns(p).rolling(20, min_periods=15).max()),
    # liquidity
    FactorDefinition("turnover_20d", "liquidity", "mean(amount / float market cap, 20)",
                     lambda p: _turnover(p).rolling(20, min_periods=15).mean()),
    FactorDefinition("abnormal_turnover", "liquidity",
                     "mean(turnover, 20) / mean(turnover, 120)",
                     lambda p: _turnover(p).rolling(20, min_periods=15).mean()
                     / _turnover(p).rolling(120, min_periods=90).mean()),
    FactorDefinition("log_amount_20d", "liquidity", "log(mean(amount, 20))",
                     lambda p: np.log(p["amount"].where(p["amount"] > 0)
                                      .rolling(20, min_periods=15).mean())),
    FactorDefinition("amihud_20d", "liquidity", "mean(|daily return| / amount * 1e8, 20)",
                     lambda p: (_returns(p).abs() / p["amount"].where(p["amount"] > 0) * 1e8)
                     .rolling(20, min_periods=15).mean()),
    FactorDefinition("volume_ratio_5_60", "liquidity", "mean(volume, 5) / mean(volume, 60)",
                     lambda p: p["volume"].rolling(5, min_periods=4).mean()
                     / p["volume"].rolling(60, min_periods=45).mean()),
    # value
    FactorDefinition("ep", "value", "1 / PE(TTM)", lambda p: _safe_inverse(p["pe"])),
    FactorDefinition("bp", "value", "1 / PB", lambda p: _safe_inverse(p["pb"])),
    # quality
    FactorDefinition("roe", "quality", "point-in-time ROE", lambda p: p["roe"]),
    FactorDefinition("growth", "quality", "point-in-time same-period revenue growth",
                     lambda p: p["growth"]),
    # technical signals already used by the scored baseline
    FactorDefinition("rsi14", "technical", "RSI(14)", lambda p: p["rsi14"]),
    FactorDefinition("macd_hist_norm", "technical", "MACD histogram / close",
                     lambda p: p["macd_hist"] / p["close"]),
    FactorDefinition("dist_ma20", "technical", "close / MA20 - 1",
                     lambda p: p["close"] / p["ma20"] - 1.0),
    FactorDefinition("dist_ma60", "technical", "close / MA60 - 1",
                     lambda p: p["close"] / p["ma60"] - 1.0),
    FactorDefinition("dist_ma250", "technical", "close / MA250 - 1",
                     lambda p: p["close"] / p["ma250"] - 1.0),
    FactorDefinition("high_52w", "technical", "close / max(close, 252)",
                     lambda p: p["close"] / p["close"].rolling(252, min_periods=200).max()),
    FactorDefinition("pv_flow_signal", "technical", "price-volume flow proxy (CMF + OBV)",
                     lambda p: p["price_volume_flow_signal"]),
    FactorDefinition("cmf", "technical", "Chaikin money flow (20)", lambda p: p["cmf"]),
    FactorDefinition("obv_momentum", "technical", "OBV momentum (20)",
                     lambda p: p["obv_momentum"]),
]


def compute_factors(panel: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    return {f.name: f.compute(panel).astype(float) for f in FACTORS}


# ------------------------------------------------------------------ preprocessing


def winsorize_mad(values: np.ndarray, n_mad: float = 3.0) -> np.ndarray:
    median = np.median(values)
    mad = np.median(np.abs(values - median)) * MAD_SCALE
    if mad == 0:
        return values.copy()
    return np.clip(values, median - n_mad * mad, median + n_mad * mad)


def zscore(values: np.ndarray) -> np.ndarray:
    std = values.std()
    if std == 0 or not np.isfinite(std):
        return np.zeros_like(values)
    return (values - values.mean()) / std


def neutralize(values: np.ndarray, industries: np.ndarray, log_mcap: np.ndarray) -> np.ndarray:
    """Residual of a cross-sectional OLS on industry dummies plus log market cap."""
    codes, _ = pd.factorize(industries)
    design = np.zeros((len(values), codes.max() + 2))
    design[np.arange(len(values)), codes] = 1.0
    design[:, -1] = zscore(log_mcap)
    beta, *_ = np.linalg.lstsq(design, values, rcond=None)
    return values - design @ beta


def preprocess_factors(
    raw: dict[str, pd.DataFrame],
    industry: pd.DataFrame,
    log_mcap: pd.DataFrame,
    universe: pd.DataFrame,
    min_names: int = 30,
) -> dict[str, pd.DataFrame]:
    """Per date: MAD winsorize, z-score, neutralize, z-score again.

    Only point-in-time members with a known industry and market cap enter the
    cross section; every other cell is NaN.
    """
    dates, symbols = universe.index, universe.columns
    out = {name: np.full((len(dates), len(symbols)), np.nan) for name in raw}
    base = universe.to_numpy(bool) & industry.notna().to_numpy() & np.isfinite(log_mcap.to_numpy())
    industry_values = industry.to_numpy(object)
    mcap_values = log_mcap.to_numpy(float)
    raw_values = {name: frame.reindex(index=dates, columns=symbols).to_numpy(float)
                  for name, frame in raw.items()}
    for i in range(len(dates)):
        for name, values in raw_values.items():
            mask = base[i] & np.isfinite(values[i])
            if mask.sum() < min_names:
                continue
            x = zscore(winsorize_mad(values[i, mask]))
            resid = neutralize(x, industry_values[i, mask], mcap_values[i, mask])
            out[name][i, mask] = zscore(resid)
    return {name: pd.DataFrame(v, index=dates, columns=symbols) for name, v in out.items()}


# ---------------------------------------------------------------- forward returns


def forward_open_returns(open_: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Return for a signal formed at the T close: buy T+1 open, sell T+1+h open."""
    return open_.shift(-(1 + horizon)) / open_.shift(-1) - 1.0


def purged_train_dates(calendar: pd.Index, train_end: str, horizon: int) -> pd.Index:
    """Dates whose forward-return exit (the T+1+h open) is on or before ``train_end``."""
    positions = np.arange(len(calendar)) + 1 + horizon
    exits = np.array([calendar[p] if p < len(calendar) else "9999-12-31" for p in positions])
    return calendar[exits <= train_end]


# ------------------------------------------------------------------------ metrics


def daily_ic(factor: pd.DataFrame, target: pd.DataFrame, rank: bool = True,
             min_names: int = 30) -> pd.Series:
    """Cross-sectional correlation per date (Spearman when ``rank``)."""
    target = target.reindex(index=factor.index, columns=factor.columns)
    mask = factor.notna() & target.notna()
    f, r = factor.where(mask), target.where(mask)
    if rank:
        f, r = f.rank(axis=1), r.rank(axis=1)
    f = f.sub(f.mean(axis=1), axis=0)
    r = r.sub(r.mean(axis=1), axis=0)
    denom = np.sqrt((f ** 2).sum(axis=1) * (r ** 2).sum(axis=1))
    ic = (f * r).sum(axis=1) / denom.replace(0, np.nan)
    return ic.where(mask.sum(axis=1) >= min_names).dropna()


def ic_summary(ic: pd.Series, horizon: int) -> dict[str, float | int | None]:
    n = int(len(ic))
    if n < 2:
        return {"n_dates": n, "mean": None, "std": None, "icir": None,
                "t_stat_nonoverlap": None, "hit_rate": None}
    mean, std = float(ic.mean()), float(ic.std())
    icir = mean / std if std > 0 else None
    return {
        "n_dates": n,
        "mean": mean,
        "std": std,
        "icir": icir,
        # overlapping h-day windows: scale by the number of independent periods
        "t_stat_nonoverlap": icir * math.sqrt(n / horizon) if icir is not None else None,
        "hit_rate": float((ic > 0).mean()),
    }


def quantile_assignments(factor: pd.DataFrame, n_quantiles: int = 5) -> pd.DataFrame:
    pct = factor.rank(axis=1, pct=True)
    return np.ceil(pct * n_quantiles).clip(1, n_quantiles)


def quantile_analysis(factor: pd.DataFrame, forward: pd.DataFrame, horizon: int,
                      dates: pd.Index, n_quantiles: int = 5) -> dict[str, object]:
    """Equal-weight quantile portfolios rebalanced every ``horizon`` sessions.

    Only every h-th date is used so holding periods do not overlap.
    """
    sample = dates[::horizon]
    buckets = quantile_assignments(factor.loc[sample], n_quantiles)
    fwd = forward.reindex(index=sample, columns=factor.columns)
    period = pd.DataFrame({q: fwd.where(buckets == q).mean(axis=1)
                           for q in range(1, n_quantiles + 1)}).dropna()
    if len(period) < 3:
        return {"n_periods": int(len(period))}
    spread = period[n_quantiles] - period[1]
    scale = TRADING_DAYS_PER_YEAR / horizon
    means = period.mean()
    std = float(spread.std())
    return {
        "n_periods": int(len(period)),
        "annualized_quantile_return": {str(q): float(means[q] * scale) for q in means.index},
        "long_short_annualized": float(spread.mean() * scale),
        "long_short_sharpe": float(spread.mean() / std * math.sqrt(scale)) if std > 0 else None,
        "monotonicity": _spearman(np.arange(1, n_quantiles + 1), means.to_numpy()),
        "top_quantile_turnover": _top_turnover(buckets, n_quantiles),
    }


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    ra, rb = pd.Series(a).rank().to_numpy(), pd.Series(b).rank().to_numpy()
    return float(np.corrcoef(ra, rb)[0, 1])


def _top_turnover(buckets: pd.DataFrame, n_quantiles: int) -> float | None:
    top = buckets == n_quantiles
    held = top.shift(1, fill_value=False)
    size = top.sum(axis=1)
    kept = (top & held).sum(axis=1)
    rate = (1.0 - kept / size.replace(0, np.nan)).iloc[1:]
    return float(rate.mean()) if len(rate.dropna()) else None


def factor_autocorrelation(factor: pd.DataFrame, lags: tuple[int, ...] = (1, 5, 20)) -> dict[str, float | None]:
    out = {}
    for lag in lags:
        ac = daily_ic(factor, factor.shift(lag))
        out[str(lag)] = float(ac.mean()) if len(ac) else None
    return out


def ic_decay(factor: pd.DataFrame, forward_1d: pd.DataFrame, dates: pd.Index,
             lags: tuple[int, ...] = (1, 2, 3, 5, 10, 20)) -> dict[str, float | None]:
    """Mean Rank IC of the T signal against the one-day return k-1 sessions later."""
    out = {}
    for lag in lags:
        ic = daily_ic(factor.loc[dates], forward_1d.shift(-(lag - 1)).loc[dates])
        out[str(lag)] = float(ic.mean()) if len(ic) else None
    return out


def pairwise_correlation(factors: dict[str, pd.DataFrame], dates: pd.Index,
                         step: int = 5) -> dict[str, dict[str, float]]:
    """Mean cross-sectional Spearman correlation between factors, sampled every ``step`` dates."""
    names = list(factors)
    total = np.zeros((len(names), len(names)))
    count = np.zeros_like(total)
    for day in dates[::step]:
        frame = pd.DataFrame({n: factors[n].loc[day] for n in names}).rank()
        corr = frame.corr(min_periods=30).to_numpy()
        ok = np.isfinite(corr)
        total[ok] += corr[ok]
        count[ok] += 1
    mean = np.where(count > 0, total / np.maximum(count, 1), np.nan)
    return {a: {b: (None if not np.isfinite(mean[i, j]) else round(float(mean[i, j]), 4))
                for j, b in enumerate(names)} for i, a in enumerate(names)}


def bonferroni_t_threshold(n_tests: int, alpha: float = 0.05) -> float:
    return NormalDist().inv_cdf(1.0 - alpha / (2 * n_tests))


# ------------------------------------------------------------- combined signals


def _row_zscore(frame: pd.DataFrame) -> pd.DataFrame:
    std = frame.std(axis=1, ddof=0).replace(0, np.nan)
    return frame.sub(frame.mean(axis=1), axis=0).div(std, axis=0)


def equal_weight_signal(factors: dict[str, pd.DataFrame], names: list[str]) -> pd.DataFrame:
    stacked = np.stack([factors[n].to_numpy() for n in names])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # cells with no factor stay NaN
        mean = np.nanmean(stacked, axis=0)
    first = factors[names[0]]
    return _row_zscore(pd.DataFrame(mean, index=first.index, columns=first.columns))


def _cross_section_target(forward: pd.DataFrame) -> pd.DataFrame:
    return _row_zscore(forward.rank(axis=1))


def ridge_fit(x: np.ndarray, y: np.ndarray, penalty: float) -> np.ndarray:
    """Minimize ||y - x b||^2 / n + penalty ||b||^2 (inputs already demeaned)."""
    n, k = x.shape
    return np.linalg.solve(x.T @ x / n + penalty * np.eye(k), x.T @ y / n)


def ridge_signal(
    factors: dict[str, pd.DataFrame],
    forward: pd.DataFrame,
    horizon: int,
    refit_dates: list[str],
    penalty: float,
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    """Expanding-window ridge refit on each ``refit_date``.

    The model fitted on R uses only rows whose forward-return exit open is
    strictly before R, and predicts dates in [R, next refit).
    """
    names = list(factors)
    first = factors[names[0]]
    calendar = first.index
    cube = np.stack([factors[n].to_numpy() for n in names], axis=-1)  # dates x symbols x k
    present = np.isfinite(cube).any(axis=-1)
    filled = np.nan_to_num(cube, nan=0.0)
    target = _cross_section_target(forward.reindex(index=calendar, columns=first.columns)).to_numpy()
    exit_pos = np.arange(len(calendar)) + 1 + horizon
    exit_dates = np.array([calendar[p] if p < len(calendar) else "9999-12-31" for p in exit_pos])
    prediction = np.full(first.shape, np.nan)
    fits = []
    bounds = list(refit_dates) + ["9999-12-31"]
    for start, stop in zip(bounds[:-1], bounds[1:]):
        rows = exit_dates < start
        sel = present[rows] & np.isfinite(target[rows])
        x = filled[rows][sel]
        y = target[rows][sel]
        beta = ridge_fit(x, y, penalty)
        apply = (calendar >= start) & (calendar < stop)
        block = filled[apply] @ beta
        block[~present[apply]] = np.nan
        prediction[apply] = block
        fits.append({
            "refit_date": start,
            "train_rows": int(len(y)),
            "train_last_signal_date": str(calendar[rows][-1]) if rows.any() else None,
            "coefficients": {n: round(float(b), 5) for n, b in zip(names, beta)},
        })
    return _row_zscore(pd.DataFrame(prediction, index=calendar, columns=first.columns)), fits


# ------------------------------------------------------------------------- study


def evaluate_signal(
    signal: pd.DataFrame,
    forwards: dict[int, pd.DataFrame],
    split_dates: dict[str, dict[int, pd.Index]],
) -> dict[str, object]:
    """IC, quantile, decay and turnover metrics for each split and horizon."""
    result: dict[str, object] = {}
    for split, by_horizon in split_dates.items():
        block: dict[str, object] = {"rank_ic": {}, "ic": {}, "quantiles": {}}
        for horizon, dates in by_horizon.items():
            if horizon not in forwards:
                continue
            fwd = forwards[horizon]
            block["rank_ic"][str(horizon)] = ic_summary(
                daily_ic(signal.loc[dates], fwd.loc[dates], rank=True), horizon)
            block["ic"][str(horizon)] = ic_summary(
                daily_ic(signal.loc[dates], fwd.loc[dates], rank=False), horizon)
            block["quantiles"][str(horizon)] = quantile_analysis(signal, fwd, horizon, dates)
        decay_dates = by_horizon[max(by_horizon)]
        block["ic_decay"] = ic_decay(signal, forwards[1], decay_dates)
        block["autocorrelation"] = factor_autocorrelation(signal.loc[by_horizon[1]])
        result[split] = block
    return result


def run_study(
    panel: dict[str, pd.DataFrame],
    universe: pd.DataFrame,
    industry: pd.DataFrame,
    log_mcap: pd.DataFrame,
    train_end: str,
    holdout_start: str,
    horizons: tuple[int, ...] = (1, 5, 20),
    primary_horizon: int = 5,
    ridge_penalty: float = 0.1,
    stress_window: tuple[str, str] | None = None,
) -> dict[str, object]:
    """Evaluate every factor and the two combined signals.

    ``stress_window`` (inclusive dates) adds a hold-out view of the combined
    signals with that window removed, to show how much a single episode drives them.
    """
    calendar = universe.index
    raw = compute_factors(panel)
    factors = preprocess_factors(raw, industry, log_mcap, universe)
    forwards = {h: forward_open_returns(panel["open"].reindex_like(universe), h)
                for h in sorted(set(horizons) | {1, 20})}
    holdout = calendar[calendar >= holdout_start]
    split_dates = {
        "train": {h: purged_train_dates(calendar, train_end, h) for h in forwards},
        "holdout": {h: holdout for h in forwards},
    }
    member_cells = int(universe.to_numpy().sum())
    evaluations = {}
    for definition in FACTORS:
        frame = factors[definition.name]
        evaluations[definition.name] = {
            "category": definition.category,
            "formula": definition.formula,
            "coverage": float(frame.notna().to_numpy().sum() / member_cells),
            **evaluate_signal(frame, forwards, split_dates),
        }

    key = str(primary_horizon)
    selected = [n for n, e in evaluations.items()
                if (e["train"]["rank_ic"][key]["icir"] or 0) > 0]
    combos = {}
    if selected:
        combos["equal_weight"] = {
            "factors": selected,
            **evaluate_signal(equal_weight_signal(factors, selected), forwards, split_dates),
        }
    refit_dates = []
    year = int(holdout_start[:4])
    while f"{year}{holdout_start[4:]}" <= calendar[-1]:
        refit_dates.append(f"{year}{holdout_start[4:]}")
        year += 1
    ridge, fits = ridge_signal(factors, forwards[primary_horizon], primary_horizon,
                               refit_dates, ridge_penalty)
    combos["ridge"] = {
        "penalty": ridge_penalty,
        "target": f"cross-sectional z-scored rank of the {primary_horizon}-day forward return",
        "fits": fits,
        **evaluate_signal(ridge, forwards, {"holdout": split_dates["holdout"]}),
    }
    if stress_window is not None:
        kept = holdout[(holdout < stress_window[0]) | (holdout > stress_window[1])]
        signals = {"ridge": ridge}
        if selected:
            signals["equal_weight"] = equal_weight_signal(factors, selected)
        for label, signal in signals.items():
            combos[label]["holdout_ex_window"] = {
                "window": list(stress_window),
                **evaluate_signal(signal, forwards, {"holdout": {h: kept for h in forwards}})["holdout"],
            }

    n_tests = len(FACTORS) * len(horizons)
    threshold = bonferroni_t_threshold(n_tests)
    train_t = [e["train"]["rank_ic"][str(h)]["t_stat_nonoverlap"]
               for e in evaluations.values() for h in horizons]
    holdout_sign = [
        (e["train"]["rank_ic"][key]["mean"] or 0) * (e["holdout"]["rank_ic"][key]["mean"] or 0) > 0
        for e in evaluations.values()
    ]
    return {
        "calendar": {"first": calendar[0], "last": calendar[-1], "sessions": len(calendar)},
        "split": {
            "train_end": train_end,
            "holdout_start": holdout_start,
            "train_signal_dates": {str(h): len(d) for h, d in split_dates["train"].items()},
            "holdout_signal_dates": int(len(holdout)),
            "purge": "a training signal date is kept only if its T+1+h exit open is on or "
                     "before train_end",
        },
        "horizons": list(horizons),
        "primary_horizon": primary_horizon,
        "multiple_testing": {
            "factors_tested": len(FACTORS),
            "horizons_tested": len(horizons),
            "tests": n_tests,
            "bonferroni_t_threshold_5pct": threshold,
            "train_abs_t_above_2": sum(1 for t in train_t if t is not None and abs(t) > 2),
            "train_abs_t_above_bonferroni": sum(1 for t in train_t
                                                if t is not None and abs(t) > threshold),
            "expected_abs_t_above_2_by_chance": round(0.0455 * n_tests, 1),
            "primary_horizon_sign_kept_in_holdout": sum(holdout_sign),
        },
        "factors": evaluations,
        "correlation_train": pairwise_correlation(factors, split_dates["train"][1]),
        "combined": combos,
    }
