"""Pure-Python metrics for re-evaluating a daily backtest against benchmarks.

Every function takes plain daily simple-return sequences so the formal report
artifacts can be re-analysed without touching the strategy or its evidence.
Conventions match ``reports.performance``: 252 periods per year, sample
standard deviation, and a zero risk-free rate unless one is passed.
"""

from __future__ import annotations

import math
import random
from statistics import NormalDist
from typing import Callable, Sequence

TRADING_DAYS_PER_YEAR = 252
EULER_GAMMA = 0.5772156649015329
_NORMAL = NormalDist()


def simple_returns(levels: Sequence[float]) -> list[float]:
    return [current / previous - 1.0 for previous, current in zip(levels, levels[1:])]


def growth(returns: Sequence[float]) -> float:
    value = 1.0
    for item in returns:
        value *= 1.0 + item
    return value


def total_return(returns: Sequence[float]) -> float:
    return growth(returns) - 1.0


def annualized_return(returns: Sequence[float], periods: int = TRADING_DAYS_PER_YEAR) -> float:
    if not returns:
        return 0.0
    return growth(returns) ** (periods / len(returns)) - 1.0


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _std(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def annualized_volatility(returns: Sequence[float], periods: int = TRADING_DAYS_PER_YEAR) -> float:
    return _std(returns) * math.sqrt(periods)


def sharpe_ratio(
    returns: Sequence[float],
    risk_free_annual: float = 0.0,
    periods: int = TRADING_DAYS_PER_YEAR,
) -> float:
    excess = [value - risk_free_annual / periods for value in returns]
    std_dev = _std(excess)
    if std_dev == 0:
        return 0.0
    return _mean(excess) / std_dev * math.sqrt(periods)


def max_drawdown(returns: Sequence[float]) -> float:
    peak = 1.0
    value = 1.0
    worst = 0.0
    for item in returns:
        value *= 1.0 + item
        peak = max(peak, value)
        worst = max(worst, 1.0 - value / peak)
    return worst


def summarize(returns: Sequence[float], risk_free_annual: float = 0.0) -> dict[str, float]:
    return {
        "days": len(returns),
        "growth_multiple": growth(returns),
        "total_return": total_return(returns),
        "annualized_return": annualized_return(returns),
        "annualized_volatility": annualized_volatility(returns),
        "sharpe": sharpe_ratio(returns, risk_free_annual),
        "max_drawdown": max_drawdown(returns),
    }


def beta_alpha_correlation(y: Sequence[float], x: Sequence[float]) -> dict[str, float]:
    """Single-factor OLS of ``y`` on ``x`` with an intercept."""
    if len(y) != len(x) or len(y) < 2:
        raise ValueError("beta needs two aligned series with at least two points")
    mean_y = _mean(y)
    mean_x = _mean(x)
    cov = sum((a - mean_y) * (b - mean_x) for a, b in zip(y, x)) / (len(y) - 1)
    var_x = _std(x) ** 2
    var_y = _std(y) ** 2
    beta = cov / var_x if var_x else 0.0
    correlation = cov / math.sqrt(var_x * var_y) if var_x and var_y else 0.0
    return {
        "beta": beta,
        "alpha_daily": mean_y - beta * mean_x,
        "correlation": correlation,
    }


def capture_ratios(y: Sequence[float], x: Sequence[float]) -> dict[str, float]:
    """Mean strategy return on benchmark up/down days over the benchmark mean."""
    up = [(a, b) for a, b in zip(y, x) if b > 0]
    down = [(a, b) for a, b in zip(y, x) if b < 0]

    def ratio(pairs: list[tuple[float, float]]) -> float:
        if not pairs:
            return 0.0
        return _mean([a for a, _ in pairs]) / _mean([b for _, b in pairs])

    return {"up_capture": ratio(up), "down_capture": ratio(down)}


def blended_benchmark(
    benchmark: Sequence[float],
    weights: Sequence[float] | float,
    cash_daily: float = 0.0,
) -> list[float]:
    """``w * benchmark + (1 - w) * cash`` with a constant or per-day weight."""
    if isinstance(weights, (int, float)):
        weights = [float(weights)] * len(benchmark)
    if len(weights) != len(benchmark):
        raise ValueError("weights and benchmark must be aligned")
    return [w * r + (1.0 - w) * cash_daily for w, r in zip(weights, benchmark)]


def drop_best_days(returns: Sequence[float], count: int) -> list[float]:
    """Remove the ``count`` largest daily returns, keeping the original order."""
    if count <= 0:
        return list(returns)
    ranked = sorted(range(len(returns)), key=lambda index: (-returns[index], index))
    dropped = set(ranked[:count])
    return [value for index, value in enumerate(returns) if index not in dropped]


def circular_block_bootstrap(
    series: Sequence[Sequence[float]],
    statistics: dict[str, Callable[..., float]],
    *,
    block_length: int,
    replications: int,
    seed: int,
) -> dict[str, list[float]]:
    """Resample aligned series jointly with circular blocks.

    ``statistics`` maps a name to ``f(*resampled_series) -> float``. Blocks are
    drawn with the same start indices for every series so cross-correlation is
    preserved. The generator is seeded, so results are deterministic.
    """
    length = len(series[0])
    if any(len(item) != length for item in series):
        raise ValueError("bootstrap series must be aligned")
    if block_length <= 0 or block_length > length:
        raise ValueError("block_length must be between 1 and the series length")
    rng = random.Random(seed)
    blocks = math.ceil(length / block_length)
    results: dict[str, list[float]] = {name: [] for name in statistics}
    for _ in range(replications):
        indices: list[int] = []
        for _ in range(blocks):
            start = rng.randrange(length)
            indices.extend((start + offset) % length for offset in range(block_length))
        indices = indices[:length]
        sample = [[item[index] for index in indices] for item in series]
        for name, statistic in statistics.items():
            results[name].append(statistic(*sample))
    return results


def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile, ``q`` in [0, 1]."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile needs at least one value")
    position = q * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def skewness_kurtosis(returns: Sequence[float]) -> tuple[float, float]:
    """Sample skewness and (non-excess) kurtosis using population moments."""
    mean = _mean(returns)
    m2 = _mean([(value - mean) ** 2 for value in returns])
    if m2 == 0:
        return 0.0, 3.0
    m3 = _mean([(value - mean) ** 3 for value in returns])
    m4 = _mean([(value - mean) ** 4 for value in returns])
    return m3 / m2**1.5, m4 / m2**2


def probabilistic_sharpe_ratio(
    returns: Sequence[float],
    benchmark_sharpe_annual: float = 0.0,
    periods: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """Bailey & Lopez de Prado PSR: P(true Sharpe > benchmark Sharpe)."""
    std_dev = _std(returns)
    if std_dev == 0:
        return 0.0
    sharpe_period = _mean(returns) / std_dev
    benchmark_period = benchmark_sharpe_annual / math.sqrt(periods)
    skew, kurt = skewness_kurtosis(returns)
    denominator = 1.0 - skew * sharpe_period + (kurt - 1.0) / 4.0 * sharpe_period**2
    if denominator <= 0:
        raise ValueError("non-positive PSR variance term")
    z = (sharpe_period - benchmark_period) * math.sqrt(len(returns) - 1) / math.sqrt(denominator)
    return _NORMAL.cdf(z)


def expected_max_sharpe(trials: int, sharpe_std_annual: float) -> float:
    """Expected maximum annualized Sharpe of ``trials`` zero-skill variants."""
    if trials <= 1:
        return 0.0
    return sharpe_std_annual * (
        (1.0 - EULER_GAMMA) * _NORMAL.inv_cdf(1.0 - 1.0 / trials)
        + EULER_GAMMA * _NORMAL.inv_cdf(1.0 - 1.0 / (trials * math.e))
    )


def deflated_sharpe_ratio(
    returns: Sequence[float],
    trials: int,
    sharpe_std_annual: float,
    periods: int = TRADING_DAYS_PER_YEAR,
) -> dict[str, float]:
    """DSR: PSR against the expected best Sharpe among ``trials`` null variants."""
    threshold = expected_max_sharpe(trials, sharpe_std_annual)
    return {
        "trials": trials,
        "sharpe_std_annual": sharpe_std_annual,
        "expected_max_null_sharpe": threshold,
        "deflated_sharpe_ratio": probabilistic_sharpe_ratio(returns, threshold, periods),
    }


def ols(
    y: Sequence[float],
    regressors: dict[str, Sequence[float]],
    newey_west_lags: int = 0,
) -> dict[str, object]:
    """OLS with an intercept and optional Newey-West (Bartlett) standard errors."""
    names = ["intercept", *regressors]
    rows = [[1.0, *(regressors[name][i] for name in regressors)] for i in range(len(y))]
    k = len(names)
    n = len(y)
    if n <= k:
        raise ValueError("not enough observations for OLS")
    xtx = [[sum(row[a] * row[b] for row in rows) for b in range(k)] for a in range(k)]
    xty = [sum(row[a] * value for row, value in zip(rows, y)) for a in range(k)]
    xtx_inv = _invert(xtx)
    coefficients = [sum(xtx_inv[a][b] * xty[b] for b in range(k)) for a in range(k)]
    residuals = [value - sum(c * x for c, x in zip(coefficients, row)) for row, value in zip(rows, y)]
    mean_y = _mean(y)
    ss_res = sum(item**2 for item in residuals)
    ss_tot = sum((value - mean_y) ** 2 for value in y)

    meat = [[0.0] * k for _ in range(k)]
    for lag in range(newey_west_lags + 1):
        weight = 1.0 if lag == 0 else 1.0 - lag / (newey_west_lags + 1)
        for t in range(lag, n):
            u = residuals[t] * residuals[t - lag]
            for a in range(k):
                for b in range(k):
                    term = rows[t][a] * rows[t - lag][b] * u
                    if lag:
                        term += rows[t - lag][a] * rows[t][b] * u
                    meat[a][b] += weight * term
    if newey_west_lags == 0:
        sigma2 = ss_res / (n - k)
        covariance = [[xtx_inv[a][b] * sigma2 for b in range(k)] for a in range(k)]
    else:
        left = _matmul(xtx_inv, meat)
        covariance = [[value * n / (n - k) for value in row] for row in _matmul(left, xtx_inv)]
    errors = [math.sqrt(max(covariance[a][a], 0.0)) for a in range(k)]
    return {
        "observations": n,
        "newey_west_lags": newey_west_lags,
        "r_squared": 1.0 - ss_res / ss_tot if ss_tot else 0.0,
        "coefficients": {
            name: {
                "estimate": coefficients[a],
                "std_error": errors[a],
                "t_stat": coefficients[a] / errors[a] if errors[a] else 0.0,
            }
            for a, name in enumerate(names)
        },
    }


def herfindahl(weights: Sequence[float]) -> float:
    total = sum(weights)
    if total <= 0:
        return 0.0
    return sum((value / total) ** 2 for value in weights)


def _matmul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [[sum(a[i][m] * b[m][j] for m in range(len(b))) for j in range(len(b[0]))] for i in range(len(a))]


def _invert(matrix: list[list[float]]) -> list[list[float]]:
    size = len(matrix)
    work = [list(row) + [1.0 if i == j else 0.0 for j in range(size)] for i, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(work[row][column]))
        if abs(work[pivot][column]) < 1e-18:
            raise ValueError("singular regressor matrix")
        work[column], work[pivot] = work[pivot], work[column]
        scale = work[column][column]
        work[column] = [value / scale for value in work[column]]
        for row in range(size):
            if row != column and work[row][column]:
                factor = work[row][column]
                work[row] = [a - factor * b for a, b in zip(work[row], work[column])]
    return [row[size:] for row in work]
