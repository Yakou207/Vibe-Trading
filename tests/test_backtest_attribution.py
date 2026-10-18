from __future__ import annotations

import json
import math
import random
import subprocess
import sys
from pathlib import Path

import pytest

from fintech_quant.reports.backtest_attribution import (
    annualized_return,
    beta_alpha_correlation,
    blended_benchmark,
    capture_ratios,
    circular_block_bootstrap,
    deflated_sharpe_ratio,
    drop_best_days,
    expected_max_sharpe,
    growth,
    herfindahl,
    max_drawdown,
    ols,
    percentile,
    probabilistic_sharpe_ratio,
    sharpe_ratio,
    simple_returns,
    skewness_kurtosis,
)

ROOT = Path(__file__).resolve().parents[1]


def _noise(n: int, seed: int, scale: float = 0.01) -> list[float]:
    rng = random.Random(seed)
    return [rng.gauss(0.0, scale) for _ in range(n)]


def test_returns_growth_and_annualization() -> None:
    returns = simple_returns([100.0, 110.0, 99.0])
    assert returns == pytest.approx([0.1, -0.1])
    assert growth(returns) == pytest.approx(0.99)
    assert annualized_return([0.01] * 252) == pytest.approx(1.01**252 - 1)
    assert annualized_return([0.01] * 126) == pytest.approx(1.01**252 - 1)


def test_max_drawdown_from_peak() -> None:
    returns = simple_returns([100.0, 120.0, 90.0, 130.0, 117.0])
    assert max_drawdown(returns) == pytest.approx(0.25)


def test_sharpe_matches_formula_and_risk_free_lowers_it() -> None:
    returns = [0.01, -0.005, 0.002, 0.004]
    mean = sum(returns) / 4
    std = math.sqrt(sum((r - mean) ** 2 for r in returns) / 3)
    assert sharpe_ratio(returns) == pytest.approx(mean / std * math.sqrt(252))
    assert sharpe_ratio(returns, 0.02) < sharpe_ratio(returns)


def test_beta_recovers_known_exposure_and_capture() -> None:
    market = _noise(2000, 1)
    strategy = [0.3 * m + 0.0002 for m in market]
    stats = beta_alpha_correlation(strategy, market)
    assert stats["beta"] == pytest.approx(0.3)
    assert stats["alpha_daily"] == pytest.approx(0.0002)
    assert stats["correlation"] == pytest.approx(1.0)

    pure = [0.3 * m for m in market]
    capture = capture_ratios(pure, market)
    assert capture["up_capture"] == pytest.approx(0.3)
    assert capture["down_capture"] == pytest.approx(0.3)


def test_blended_benchmark_constant_and_daily_weights() -> None:
    bench = [0.02, -0.01, 0.03]
    assert blended_benchmark(bench, 0.5) == pytest.approx([0.01, -0.005, 0.015])
    assert blended_benchmark(bench, [0.0, 1.0, 0.5], cash_daily=0.001) == pytest.approx([0.001, -0.01, 0.0155])
    with pytest.raises(ValueError):
        blended_benchmark(bench, [1.0])


def test_drop_best_days_removes_largest_returns_in_order() -> None:
    returns = [0.01, 0.05, -0.02, 0.04, 0.0]
    assert drop_best_days(returns, 2) == [0.01, -0.02, 0.0]
    assert drop_best_days(returns, 0) == returns


def test_block_bootstrap_is_deterministic_and_preserves_alignment() -> None:
    a = _noise(300, 2)
    b = [2 * x for x in a]
    stats = {"ratio": lambda x, y: sum(y) / sum(x) if sum(x) else 2.0}
    first = circular_block_bootstrap([a, b], stats, block_length=10, replications=50, seed=7)
    second = circular_block_bootstrap([a, b], stats, block_length=10, replications=50, seed=7)
    assert first == second
    assert all(value == pytest.approx(2.0) for value in first["ratio"])


def test_block_bootstrap_ci_covers_mean_of_iid_series() -> None:
    series = [x + 0.001 for x in _noise(1000, 3)]
    samples = circular_block_bootstrap(
        [series], {"mean": lambda x: sum(x) / len(x)}, block_length=20, replications=400, seed=11
    )["mean"]
    point = sum(series) / len(series)
    assert percentile(samples, 0.025) < point < percentile(samples, 0.975)


def test_percentile_interpolates() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == pytest.approx(2.5)
    assert percentile([5.0], 0.9) == 5.0


def test_skew_kurtosis_of_symmetric_series() -> None:
    skew, kurt = skewness_kurtosis([-1.0, 1.0] * 50)
    assert skew == pytest.approx(0.0)
    assert kurt == pytest.approx(1.0)


def test_psr_and_dsr_behave_monotonically() -> None:
    strong = [x + 0.002 for x in _noise(1250, 4)]
    zero = [x - sum(strong) / len(strong) for x in strong]
    assert probabilistic_sharpe_ratio(strong) > 0.99
    assert probabilistic_sharpe_ratio(zero) == pytest.approx(0.5, abs=1e-9)

    assert expected_max_sharpe(1, 0.5) == 0.0
    assert expected_max_sharpe(100, 0.5) > expected_max_sharpe(7, 0.5) > 0
    assert expected_max_sharpe(7, 1.0) == pytest.approx(2 * expected_max_sharpe(7, 0.5))

    single = deflated_sharpe_ratio(strong, 1, 0.5)["deflated_sharpe_ratio"]
    many = deflated_sharpe_ratio(strong, 100, 1.0)["deflated_sharpe_ratio"]
    assert single == pytest.approx(probabilistic_sharpe_ratio(strong))
    assert many < single


def test_ols_recovers_coefficients_with_and_without_newey_west() -> None:
    x1 = _noise(1500, 5)
    x2 = _noise(1500, 6)
    eps = _noise(1500, 7, scale=0.001)
    y = [0.0001 + 0.4 * a - 0.2 * b + e for a, b, e in zip(x1, x2, eps)]
    plain = ols(y, {"x1": x1, "x2": x2})
    robust = ols(y, {"x1": x1, "x2": x2}, newey_west_lags=5)
    for fit in (plain, robust):
        coefficients = fit["coefficients"]
        assert coefficients["x1"]["estimate"] == pytest.approx(0.4, abs=0.01)
        assert coefficients["x2"]["estimate"] == pytest.approx(-0.2, abs=0.01)
        assert fit["r_squared"] > 0.9
    ratio = robust["coefficients"]["x1"]["std_error"] / plain["coefficients"]["x1"]["std_error"]
    assert 0.7 < ratio < 1.3


def test_herfindahl() -> None:
    assert herfindahl([1.0, 1.0, 1.0, 1.0]) == pytest.approx(0.25)
    assert herfindahl([5.0]) == pytest.approx(1.0)
    assert herfindahl([]) == 0.0


def test_report_section_reader_parses_only_requested_keys(tmp_path: Path) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import analyze_backtest_attribution as script
    finally:
        sys.path.pop(0)
    report = {
        "corporate_actions": [{"symbol": "000001.SZ", "shares_after": 200}],
        "equity_curve": [{"trade_date": "2026-01-02", "equity": 1.0}],
        "run_id": "risk_controlled",
        "trades": [],
        "universe_symbols": ["000001.SZ"],
    }
    path = tmp_path / "run_report.json"
    path.write_text(json.dumps(report, indent=2))
    sections = script.read_report_sections(path, {"equity_curve", "run_id", "trades"})
    assert sections == {
        "equity_curve": report["equity_curve"],
        "run_id": "risk_controlled",
        "trades": [],
    }


def test_script_help_runs() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "analyze_backtest_attribution.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--offline" in result.stdout
