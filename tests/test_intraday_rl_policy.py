from __future__ import annotations

from fintech_quant.intraday.rl_policy import (
    CLOSE,
    HOLD,
    OPEN_BUY,
    OPEN_SELL,
    LinearQConfig,
    legal_actions,
    run_policy_day,
    train_intraday_linear_q,
)
from fintech_quant.intraday.rotation import RotationParams

PARAMS = RotationParams(z_window=6, z_min_window=3)


def _bar(dt: str, price: float):
    return {"datetime": dt, "open": price, "high": price, "low": price, "close": price, "volume": 1000.0}


def _day(prices, start=(9, 35)):
    hh, mm = start
    bars = []
    for price in prices:
        bars.append(_bar(f"2026-07-20 {hh}:{mm:02d}:00", price))
        mm += 5
        if mm >= 60:
            hh, mm = hh + 1, mm - 60
    return bars


def test_legal_actions_masking() -> None:
    assert legal_actions(leg_side=0, budget_ok=True, forcing=False, z_ready=True) == [HOLD, OPEN_SELL, OPEN_BUY]
    assert legal_actions(leg_side=0, budget_ok=False, forcing=False, z_ready=True) == [HOLD]
    assert legal_actions(leg_side=0, budget_ok=True, forcing=False, z_ready=False) == [HOLD]
    assert legal_actions(leg_side=-1, budget_ok=True, forcing=False, z_ready=True) == [HOLD, CLOSE]
    assert legal_actions(leg_side=1, budget_ok=True, forcing=True, z_ready=True) == [CLOSE]


def test_policy_day_is_always_balanced_even_for_greedy_seller() -> None:
    # A policy that opens a sell leg at the first chance and never closes it
    # voluntarily must still end flat via the forced close.
    def stubborn(state, legal):
        if OPEN_SELL in legal:
            return OPEN_SELL
        return HOLD if HOLD in legal else legal[0]

    bars = _day([10.0, 10.0, 10.01, 9.99, 10.0, 10.0, 10.1, 10.1, 10.1, 10.1])
    result = run_policy_day(bars, base_shares=500, policy=stubborn, params=PARAMS)

    assert result.end_shares_match_base
    assert len(result.trades) % 2 == 0


def test_policy_day_respects_t_plus_one_budget() -> None:
    # Open/close as fast as possible; the sellable budget must cap sells at base.
    def churner(state, legal):
        if OPEN_SELL in legal:
            return OPEN_SELL
        if CLOSE in legal:
            return CLOSE
        return HOLD

    bars = _day([10.0] * 20)
    result = run_policy_day(bars, base_shares=500, policy=churner, params=PARAMS)

    sold = sum(t["shares"] for t in result.trades if t["action"] == "sell")
    assert sold <= 500
    assert result.end_shares_match_base


def test_training_is_deterministic_per_seed_and_finite() -> None:
    bars = _day([10.0, 10.0, 10.05, 9.95, 10.0, 10.02, 10.4, 10.35, 10.0, 10.0, 10.01, 10.0])
    episodes = [("600000.SH", bars, 500)]
    config = LinearQConfig(episodes=5)

    run_a = train_intraday_linear_q(episodes, params=PARAMS, config=config, seed=7)
    run_b = train_intraday_linear_q(episodes, params=PARAMS, config=config, seed=7)
    run_c = train_intraday_linear_q(episodes, params=PARAMS, config=config, seed=8)

    assert run_a.policy.weights == run_b.policy.weights
    assert run_a.episode_pnls == run_b.episode_pnls
    assert all(abs(p) < 1e12 for p in run_a.episode_pnls + run_c.episode_pnls)


def test_hold_only_policy_produces_zero_pnl() -> None:
    def hold(state, legal):
        return HOLD if HOLD in legal else legal[0]

    bars = _day([10.0, 10.1, 9.9, 10.2, 10.0, 10.1, 10.0, 9.95, 10.05, 10.0])
    result = run_policy_day(bars, base_shares=500, policy=hold, params=PARAMS)

    assert result.trades == []
    assert result.enhancement_pnl == 0.0
