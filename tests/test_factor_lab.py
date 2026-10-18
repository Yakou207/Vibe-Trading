from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fintech_quant.research.factor_lab import (
    FACTORS,
    compute_factors,
    daily_ic,
    equal_weight_signal,
    forward_open_returns,
    ic_summary,
    preprocess_factors,
    purged_train_dates,
    quantile_analysis,
    ridge_signal,
    winsorize_mad,
)

N_DATES, N_SYMBOLS = 320, 60


def _calendar(n: int = N_DATES) -> pd.Index:
    return pd.Index([d.strftime("%Y-%m-%d") for d in pd.bdate_range("2023-01-02", periods=n)])


def _frame(values: np.ndarray, dates: pd.Index | None = None) -> pd.DataFrame:
    dates = _calendar(values.shape[0]) if dates is None else dates
    return pd.DataFrame(values, index=dates, columns=[f"S{i:03d}" for i in range(values.shape[1])])


def _panel(seed: int = 0) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    close = 10 * np.exp(np.cumsum(rng.normal(0, 0.02, (N_DATES, N_SYMBOLS)), axis=0))
    panel = {
        "close": close,
        "open": close * (1 + rng.normal(0, 0.005, close.shape)),
        "volume": rng.uniform(1e6, 2e6, close.shape),
        "amount": rng.uniform(1e8, 2e8, close.shape),
        "float_mcap": rng.uniform(1e10, 2e10, close.shape),
        "pe": rng.uniform(5, 50, close.shape),
        "pb": rng.uniform(0.5, 5, close.shape),
        "roe": rng.normal(0.1, 0.05, close.shape),
        "growth": rng.normal(0.1, 0.2, close.shape),
        "rsi14": rng.uniform(20, 80, close.shape),
        "macd_hist": rng.normal(0, 0.1, close.shape),
        "ma20": close * 0.99,
        "ma60": close * 0.98,
        "ma250": close * 0.97,
        "price_volume_flow_signal": rng.normal(0, 1, close.shape),
        "cmf": rng.normal(0, 1, close.shape),
        "obv_momentum": rng.normal(0, 1, close.shape),
    }
    return {k: _frame(v) for k, v in panel.items()}


def test_factor_library_size_and_unique_names():
    names = [f.name for f in FACTORS]
    assert 20 <= len(names) <= 30
    assert len(set(names)) == len(names)


def test_ic_sign_follows_planted_signal():
    rng = np.random.default_rng(1)
    target = _frame(rng.normal(0, 1, (100, N_SYMBOLS)))
    noise = _frame(rng.normal(0, 1, (100, N_SYMBOLS)))
    good = target + noise
    for rank in (True, False):
        assert daily_ic(good, target, rank=rank).mean() > 0.5
        assert daily_ic(-good, target, rank=rank).mean() < -0.5
        assert abs(daily_ic(noise, target, rank=rank).mean()) < 0.05
    summary = ic_summary(daily_ic(good, target), horizon=1)
    assert summary["icir"] > 3 and summary["hit_rate"] == 1.0


def test_winsorize_mad_clips_outliers_only():
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 1000.0])
    clipped = winsorize_mad(values)
    assert clipped[-1] < 20
    np.testing.assert_allclose(clipped[:5], values[:5])


def test_neutralization_removes_industry_and_size_exposure():
    rng = np.random.default_rng(2)
    n_dates = 40
    dates = _calendar(n_dates)
    industries = np.array(["bank", "tech", "energy"])[np.arange(N_SYMBOLS) % 3]
    industry = _frame(np.tile(industries, (n_dates, 1)).astype(object), dates)
    log_mcap = _frame(rng.normal(23, 1, (n_dates, N_SYMBOLS)), dates)
    effect = np.where(industries == "tech", 5.0, np.where(industries == "bank", -5.0, 0.0))
    raw = _frame(effect + 2.0 * log_mcap.to_numpy() + rng.normal(0, 1, (n_dates, N_SYMBOLS)), dates)
    universe = _frame(np.ones((n_dates, N_SYMBOLS), bool), dates)

    out = preprocess_factors({"f": raw}, industry, log_mcap, universe)["f"]

    for day in dates:
        row = out.loc[day]
        assert abs(row.mean()) < 1e-9 and abs(row.std(ddof=0) - 1) < 1e-9
        for name in industries[:3]:
            assert abs(row[industries == name].mean()) < 1e-9
        assert abs(np.corrcoef(row, log_mcap.loc[day])[0, 1]) < 1e-9
    # before neutralization the industry exposure is large
    assert raw.loc[dates[0]][industries == "tech"].mean() - raw.loc[dates[0]].mean() > 3


def test_preprocessing_respects_point_in_time_universe():
    dates = _calendar(5)
    rng = np.random.default_rng(3)
    raw = _frame(rng.normal(0, 1, (5, N_SYMBOLS)), dates)
    industry = _frame(np.full((5, N_SYMBOLS), "x", object), dates)
    log_mcap = _frame(rng.normal(23, 1, (5, N_SYMBOLS)), dates)
    members = np.ones((5, N_SYMBOLS), bool)
    members[:, :10] = False
    out = preprocess_factors({"f": raw}, industry, log_mcap, _frame(members, dates))["f"]
    assert out.iloc[:, :10].isna().all().all()
    assert out.iloc[:, 10:].notna().all().all()


def test_forward_return_is_next_open_to_open_and_ignores_the_past():
    rng = np.random.default_rng(4)
    open_ = _frame(np.exp(np.cumsum(rng.normal(0, 0.02, (30, 4)), axis=0)))
    for horizon in (1, 5, 20):
        fwd = forward_open_returns(open_, horizon)
        t = 3
        expected = open_.iloc[t + 1 + horizon] / open_.iloc[t + 1] - 1
        pd.testing.assert_series_equal(fwd.iloc[t], expected, check_names=False)
        # changing every price up to and including T leaves the T forward return unchanged
        shocked = open_.copy()
        shocked.iloc[: t + 1] *= 3.0
        pd.testing.assert_series_equal(forward_open_returns(shocked, horizon).iloc[t], fwd.iloc[t])
        # the last 1+h dates have no realized forward return
        assert fwd.iloc[-(1 + horizon):].isna().all().all()


def test_factors_do_not_look_ahead():
    panel = _panel()
    base = compute_factors(panel)
    t = 280
    shocked = {k: v.copy() for k, v in panel.items()}
    for frame in shocked.values():
        frame.iloc[t + 1:] = frame.iloc[t + 1:] * 1.7
    after = compute_factors(shocked)
    for name in base:
        pd.testing.assert_frame_equal(base[name].iloc[: t + 1], after[name].iloc[: t + 1],
                                      obj=name)


def test_purged_training_dates_end_before_split():
    calendar = _calendar(30)
    split = calendar[19]
    for horizon in (1, 5):
        kept = purged_train_dates(calendar, split, horizon)
        last = calendar.get_loc(kept[-1])
        assert calendar[last + 1 + horizon] <= split
        assert calendar[last + 2 + horizon] > split


def test_quantile_spread_is_monotonic_for_planted_signal():
    rng = np.random.default_rng(5)
    dates = _calendar(200)
    signal = _frame(rng.normal(0, 1, (200, N_SYMBOLS)), dates)
    forward = 0.01 * signal + _frame(rng.normal(0, 0.01, (200, N_SYMBOLS)), dates)
    result = quantile_analysis(signal, forward, horizon=5, dates=dates)
    assert result["n_periods"] == 40
    assert result["long_short_annualized"] > 0
    assert result["monotonicity"] == pytest.approx(1.0)


def test_equal_weight_signal_averages_and_restandardizes():
    dates = _calendar(3)
    a = _frame(np.tile(np.arange(N_SYMBOLS, dtype=float), (3, 1)), dates)
    combo = equal_weight_signal({"a": a, "b": a * 2}, ["a", "b"])
    assert abs(combo.iloc[0].mean()) < 1e-9
    assert np.corrcoef(combo.iloc[0], a.iloc[0])[0, 1] == pytest.approx(1.0)


def test_ridge_uses_only_returns_realized_before_refit():
    rng = np.random.default_rng(6)
    dates = _calendar(120)
    good = _frame(rng.normal(0, 1, (120, N_SYMBOLS)), dates)
    junk = _frame(rng.normal(0, 1, (120, N_SYMBOLS)), dates)
    forward = good + 0.5 * _frame(rng.normal(0, 1, (120, N_SYMBOLS)), dates)
    refit = [dates[80]]
    signal, fits = ridge_signal({"good": good, "junk": junk}, forward, 5, refit, penalty=0.1)
    assert fits[0]["coefficients"]["good"] > 0.5
    assert abs(fits[0]["coefficients"]["junk"]) < 0.1
    assert signal.loc[: dates[79]].isna().all().all()
    assert daily_ic(signal.loc[dates[80]:], forward.loc[dates[80]:]).mean() > 0.5
    # the last usable training signal date exits strictly before the refit date
    assert fits[0]["train_last_signal_date"] == dates[80 - 1 - 5 - 1]
    # scrambling returns whose exit is on or after the refit date changes nothing
    scrambled = forward.copy()
    scrambled.loc[dates[80 - 1 - 5]:] = rng.normal(0, 1, scrambled.loc[dates[80 - 1 - 5]:].shape)
    _, fits_scrambled = ridge_signal({"good": good, "junk": junk}, scrambled, 5, refit, penalty=0.1)
    assert fits_scrambled[0]["coefficients"] == fits[0]["coefficients"]


def test_run_study_reports_split_holdout_and_multiple_testing():
    from fintech_quant.research.factor_lab import run_study

    panel = _panel(7)
    dates = panel["close"].index
    rng = np.random.default_rng(8)
    universe = _frame(np.ones((N_DATES, N_SYMBOLS), bool), dates)
    industry = _frame(np.tile(np.array(["a", "b", "c"])[np.arange(N_SYMBOLS) % 3],
                              (N_DATES, 1)).astype(object), dates)
    log_mcap = _frame(rng.normal(23, 1, (N_DATES, N_SYMBOLS)), dates)
    train_end, holdout_start = dates[199], dates[200]

    window = (dates[250], dates[269])
    study = run_study(panel, universe, industry, log_mcap, train_end, holdout_start,
                      stress_window=window)

    assert study["multiple_testing"]["factors_tested"] == len(FACTORS)
    assert study["multiple_testing"]["tests"] == len(FACTORS) * 3
    assert study["split"]["holdout_signal_dates"] == N_DATES - 200
    assert set(study["factors"]) == {f.name for f in FACTORS}
    ridge = study["combined"]["ridge"]
    assert ridge["fits"][0]["refit_date"] == holdout_start
    assert ridge["fits"][0]["train_last_signal_date"] < train_end
    stressed = ridge["holdout_ex_window"]
    assert stressed["window"] == list(window)
    assert stressed["rank_ic"]["1"]["n_dates"] < ridge["holdout"]["rank_ic"]["1"]["n_dates"]
    # random data: no factor should look strong out of sample
    for e in study["factors"].values():
        mean = e["holdout"]["rank_ic"]["5"]["mean"]
        assert mean is None or abs(mean) < 0.1
