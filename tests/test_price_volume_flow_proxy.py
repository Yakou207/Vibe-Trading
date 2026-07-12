from __future__ import annotations


def test_price_volume_proxy_uses_only_current_and_prior_bars() -> None:
    from fintech_quant.data.price_volume_flow import materialize_price_volume_flow_proxy

    bars = [
        _bar("2026-01-02", high=11.0, low=9.0, close=10.0, volume=100.0),
        _bar("2026-01-05", high=11.0, low=9.0, close=11.0, volume=200.0),
        _bar("2026-01-06", high=11.0, low=9.0, close=9.0, volume=100.0),
    ]

    original = materialize_price_volume_flow_proxy(
        bars,
        window=3,
        source_fetched_at="2026-07-11T13:00:00+08:00",
    )
    with_future = materialize_price_volume_flow_proxy(
        bars + [_bar("2026-01-07", high=20.0, low=8.0, close=8.0, volume=10000.0)],
        window=3,
        source_fetched_at="2026-07-11T13:00:00+08:00",
    )

    assert len(original) == 1
    assert original[0] == with_future[0]
    assert original[0].trade_date.isoformat() == "2026-01-06"
    assert original[0].available_date == original[0].trade_date
    assert original[0].source == "derived_price_volume_cmf_obv_v1"
    assert original[0].values == {
        "flow_proxy_kind": "price_volume_cmf_obv",
        "flow_proxy_window": 3,
        "price_volume_flow_signal": 0.25,
        "price_volume_outflow_days": 0,
        "cmf": 0.25,
        "obv_momentum": 0.25,
        "main_net_inflow": None,
        "main_outflow_days": None,
        "margin_financing_positive": None,
    }


def _bar(trade_date: str, *, high: float, low: float, close: float, volume: float):
    return {
        "symbol": "000001.SZ",
        "trade_date": trade_date,
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "amount": close * volume,
        "source": "fixture",
    }
