from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fintech_quant.research.factor_lab import purged_train_dates
from fintech_quant.research.scoring_v2 import (
    CATEGORIES,
    FACTOR_NAMES,
    category_scores,
    category_weights,
    current_score_summary,
    fit_scoring_v2,
    run_scoring_v2_study,
    score_scoring_v2,
)

N_DATES, N_SYMBOLS = 200, 80
TRAIN_END = "2023-07-31"


def _calendar(n: int = N_DATES) -> pd.Index:
    return pd.Index([d.strftime("%Y-%m-%d") for d in pd.bdate_range("2023-01-02", periods=n)])


def _frame(values: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame(values, index=_calendar(values.shape[0]),
                        columns=[f"S{i:03d}" for i in range(values.shape[1])])


def _planted(seed: int = 0) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Neutralized-style factor z-scores plus a forward return driven by two of them.

    ``vol_60d`` predicts negatively and ``ep`` positively; the rest is noise.
    """
    rng = np.random.default_rng(seed)
    factors = {n: _frame(rng.normal(0, 1, (N_DATES, N_SYMBOLS))) for n in FACTOR_NAMES}
    forward = 0.6 * factors["ep"] - 0.6 * factors["vol_60d"] + _frame(
        rng.normal(0, 1, (N_DATES, N_SYMBOLS)))
    return factors, forward


def _train_dates() -> pd.Index:
    return purged_train_dates(_calendar(), TRAIN_END, 5)


def test_signs_follow_training_icir_not_expected_signs() -> None:
    factors, forward = _planted()
    factors["roe"] = -factors["ep"]  # roe is "expected +" but predicts negatively here

    fit = fit_scoring_v2(factors, forward, _train_dates())

    assert fit.signs["ep"] == 1
    assert fit.signs["vol_60d"] == -1
    assert fit.signs["roe"] == -1
    assert fit.category_train_icir["value"] > 0.5
    assert fit.category_train_icir["low_risk"] > 0.5
    assert fit.category_train_icir["quality_growth"] > 0.3
    assert sum(fit.weights.values()) == pytest.approx(1.0)
    assert fit.weights["value"] > fit.weights["momentum"]


def test_category_weights_clip_negative_and_reject_all_nonpositive() -> None:
    weights = category_weights({"a": 0.3, "b": -0.2, "c": 0.1, "d": None})

    assert weights == pytest.approx({"a": 0.75, "b": 0.0, "c": 0.25, "d": 0.0})
    with pytest.raises(ValueError):
        category_weights({"a": -0.1, "b": 0.0})


def test_missing_input_is_neutral_and_lowers_coverage() -> None:
    factors, forward = _planted(1)
    fit = fit_scoring_v2(factors, forward, _train_dates())
    day, stock = factors["ep"].index[-1], "S000"
    for name in CATEGORIES["value"]:
        factors[name].loc[day, stock] = np.nan
    factors["rev_5d"].loc[day, "S001"] = np.nan

    result = score_scoring_v2(factors, fit)

    assert result.categories["value"].loc[day, stock] == pytest.approx(0.0, abs=1e-12)
    assert result.coverage.loc[day, stock] == pytest.approx(7 / 9)
    assert result.coverage.loc[day, "S001"] == pytest.approx(8 / 9)
    assert result.coverage.loc[day, "S002"] == 1.0
    assert np.isfinite(result.score.loc[day, stock])
    # a missing factor scores exactly like a present factor at z = 0
    filled = {n: f.copy() for n, f in factors.items()}
    filled["rev_5d"].loc[day, "S001"] = 0.0
    assert score_scoring_v2(filled, fit).composite.loc[day, "S001"] == pytest.approx(
        result.composite.loc[day, "S001"])


def test_stock_with_no_inputs_is_not_scored() -> None:
    factors, forward = _planted(2)
    fit = fit_scoring_v2(factors, forward, _train_dates())
    day = factors["ep"].index[-1]
    for name in FACTOR_NAMES:
        factors[name].loc[day, "S005"] = np.nan

    result = score_scoring_v2(factors, fit)

    assert result.coverage.loc[day, "S005"] == 0.0
    assert np.isnan(result.score.loc[day, "S005"])
    assert result.score.loc[day].notna().sum() == N_SYMBOLS - 1


def test_percentile_bounds_and_order() -> None:
    factors, forward = _planted(3)
    fit = fit_scoring_v2(factors, forward, _train_dates())

    result = score_scoring_v2(factors, fit)

    values = result.score.to_numpy()
    assert np.nanmin(values) > 0.0 and np.nanmax(values) == 100.0
    row = result.score.iloc[-1]
    assert row.rank().equals(result.composite.iloc[-1].rank())


def test_fit_ignores_holdout_and_score_ignores_later_dates() -> None:
    factors, forward = _planted(4)
    train = _train_dates()
    fit = fit_scoring_v2(factors, forward, train)
    base = score_scoring_v2(factors, fit).score

    rng = np.random.default_rng(99)
    after = factors["ep"].index > TRAIN_END
    shocked_forward = forward.copy()
    shocked_forward.loc[after] = rng.normal(0, 5, shocked_forward.loc[after].shape)
    shocked = {n: f.copy() for n, f in factors.items()}
    for frame in shocked.values():
        frame.loc[after] = rng.normal(0, 1, frame.loc[after].shape)
    assert fit_scoring_v2(shocked, shocked_forward, train) == fit

    # changing every date after T leaves the score on T unchanged
    day = factors["ep"].index[150]
    later = factors["ep"].index > day
    future = {n: f.copy() for n, f in factors.items()}
    for frame in future.values():
        frame.loc[later] = rng.normal(0, 1, frame.loc[later].shape)
    rescored = score_scoring_v2(future, fit).score
    pd.testing.assert_frame_equal(rescored.loc[:day], base.loc[:day])


def test_current_score_summary_counts_gate_and_values() -> None:
    days = _calendar(30)
    symbols = [f"S{i:03d}" for i in range(40)]
    rng = np.random.default_rng(5)
    total = pd.DataFrame(rng.choice([40.0, 60.0, 75.0], (30, 40)), index=days, columns=symbols)
    confidence = pd.DataFrame(0.8125, index=days, columns=symbols)
    confidence.iloc[:, :10] = 0.75
    forward = pd.DataFrame(rng.normal(0, 1, (30, 40)), index=days, columns=symbols)
    dates = {"train": {5: days[:20], 20: days[:20]}}

    summary = current_score_summary(total, confidence, {"technical": total / 3},
                                    {5: forward, 20: forward}, dates, 70.0, 0.8)

    assert summary["distinct_totals"] == 3
    assert summary["max_total"] == 75.0
    assert summary["distinct_component_values"]["technical"] == 3
    assert summary["share_below_confidence_gate"] == pytest.approx(0.25)
    assert summary["share_above_threshold_blocked_by_gate"] == pytest.approx(
        float((total.iloc[:, :10] >= 70).to_numpy().sum() / (total >= 70).to_numpy().sum()))


def test_study_runs_end_to_end_on_a_synthetic_panel() -> None:
    from test_factor_lab import _panel  # noqa: PLC0415

    panel = _panel(0)
    dates, symbols = panel["close"].index, panel["close"].columns
    universe = pd.DataFrame(True, index=dates, columns=symbols)
    industry = pd.DataFrame([[f"I{i % 4}" for i in range(len(symbols))]] * len(dates),
                            index=dates, columns=symbols)
    log_mcap = np.log(panel["float_mcap"])
    holdout_start = dates[260]

    study, result, _, _ = run_scoring_v2_study(
        panel, universe, industry, log_mcap, dates[250], holdout_start,
        (dates[270], dates[280]))

    assert study["design"]["variants_evaluated_on_holdout"] == 1
    assert sum(study["fit"]["weights"].values()) == pytest.approx(1.0)
    assert set(study["composite"]) == {"train", "holdout", "holdout_ex_window"}
    assert study["split"]["signal_dates"]["holdout_ex_window"]["5"] == 60 - 11
    assert np.nanmax(result.score.to_numpy()) <= 100.0
