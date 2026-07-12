from __future__ import annotations

from datetime import date


def test_a_share_sell_cost_uses_reduced_stamp_duty_from_2023_08_28() -> None:
    from fintech_quant.backtesting.costs import AShareCostModel

    model = AShareCostModel(commission_rate=0.0003, minimum_commission=5.0)

    before = model.sell_cost(10_000.0, date(2023, 8, 25))
    after = model.sell_cost(10_000.0, date(2023, 8, 28))

    assert before.commission == 5.0
    assert before.stamp_duty == 10.0
    assert before.total == 15.0
    assert after.commission == 5.0
    assert after.stamp_duty == 5.0
    assert after.total == 10.0


def test_a_share_buy_cost_has_no_stamp_duty() -> None:
    from fintech_quant.backtesting.costs import AShareCostModel

    cost = AShareCostModel().buy_cost(100_000.0, date(2026, 1, 5))

    assert cost.commission == 30.0
    assert cost.stamp_duty == 0.0
    assert cost.total == 30.0
