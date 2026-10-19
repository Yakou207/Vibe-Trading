from __future__ import annotations

from pathlib import Path

import pytest

from fintech_quant.reports.picker import PickerData, picks_payload, resolve_symbol, stock_payload
from fintech_quant.research import momentum_pool_v2
from fintech_quant.research.momentum_pool import initial_pool_state, step_pool
from fintech_quant.research.momentum_setup import momentum_table, screen
from scripts.refresh_momentum_pool import _require_safe_output
from test_momentum_setup import _dates, _universe


def _data() -> PickerData:
    series = _universe()
    as_of = _dates(200)[-1]
    members = set(series)
    return PickerData(
        as_of=as_of,
        series=series,
        names={"600001.SH": "领涨股份", "600002.SH": "下跌股份"},
        members=members,
        scores={"600001.SH": {"total": 75.0, "confidence": 0.85, "components": {}}},
        market_warnings={"600001.SH": ["watch: Broad index is below the 250-day moving average."]},
        price_ratio={symbol: 0.5 for symbol in series},
        screen_results=screen(series, as_of, members=members),
        momentum=momentum_table(series, as_of),
        sources={},
    )


def test_resolves_bare_code_suffix_code_and_chinese_name() -> None:
    data = _data()

    assert resolve_symbol(data, "600001") == "600001.SH"
    assert resolve_symbol(data, "600001.sh") == "600001.SH"
    assert resolve_symbol(data, "领涨") == "600001.SH"
    assert resolve_symbol(data, "不存在") is None


def test_stock_payload_scales_levels_and_combines_both_gates() -> None:
    data = _data()

    payload = stock_payload(data, "600001")

    hfq_close = data.series["600001.SH"].bars[-1].close
    assert payload["analysis"]["close"] == pytest.approx(round(hfq_close * 0.5, 3))
    assert payload["chart"]["ohlc"][-1][3] == pytest.approx(round(hfq_close * 0.5, 3))
    assert payload["rank"] == 1
    verdict = payload["verdict"]
    assert verdict["level"] == "entry"
    assert verdict["baseline_pass"] is True
    assert any("T+1" in note for note in verdict["notes"])
    assert any("250-day" in note for note in verdict["notes"])


def test_unknown_query_returns_error_payload() -> None:
    assert "error" in stock_payload(_data(), "不存在")


def test_picks_payload_lists_candidates_and_pool_view() -> None:
    data = _data()
    pool = step_pool(
        initial_pool_state(),
        as_of=data.as_of,
        series=data.series,
        screen_results=data.screen_results,
        previous_session=None,
    )

    payload = picks_payload(data, pool)

    assert payload["candidates"][0]["symbol"] == "600001.SH"
    assert payload["candidates"][0]["name"] == "领涨股份"
    assert payload["pool"]["pool"][0]["name"] == "领涨股份"
    assert payload["pool"]["metrics"]["equity"] == pytest.approx(100000.0)
    assert payload["pool"]["stale"] is False


def test_picks_payload_shows_v2_watchlist_ages_and_position_r_status() -> None:
    data = _data()
    pool_v2 = momentum_pool_v2.step_pool(
        momentum_pool_v2.initial_pool_state(),
        as_of=data.as_of,
        series=data.series,
        screen_results=data.screen_results,
        previous_session=None,
    )
    close = data.series["600002.SH"].bars[-1].close
    pool_v2["book"]["positions"]["600002.SH"] = {
        "entry_date": "2025-01-01",
        "entry_price": close / 1.02,
        "stop": close / 1.02 * 0.98,
        "shares": 10.0,
        "cost": 200.0,
        "peak_close": close,
        "sessions_held": 4,
    }

    view = picks_payload(data, None, pool_v2)["pool_v2"]

    assert view["watchlist"][0]["symbol"] == "600001.SH"
    assert view["watchlist"][0]["age"] == 0
    assert view["pending"][0]["symbol"] == "600001.SH"
    position = view["positions"]["600002.SH"]
    assert position["name"] == "下跌股份"
    assert position["r_multiple"] == pytest.approx(1.0)
    assert position["trail"] == "ema9"
    assert position["time_stop_in"] == 11
    assert view["metrics"]["brake"] == "normal"


@pytest.mark.parametrize(
    "path",
    [
        "outputs/paper_trading/csi300_baseline/cycles/pool",
        "data/paper/csi300_baseline/pool",
        "data/paper/csi300_baseline/validation/pool",
    ],
)
def test_pool_output_refuses_evidence_directories(path: str) -> None:
    with pytest.raises(ValueError, match="outside evidence directories"):
        _require_safe_output(Path(path))


def test_pool_output_accepts_dedicated_directory(tmp_path: Path) -> None:
    _require_safe_output(tmp_path / "outputs" / "momentum_pool")


def test_stock_payload_shows_research_v2_score_next_to_baseline() -> None:
    snapshot = {
        "as_of": "2020-01-01",
        "label": "研究评分 v2（横截面排名合成），不驱动计数策略",
        "signs": {"ep": 1, "roe": -1, "vol_60d": -1},
        "scores": {
            "600001.SH": {
                "score": 87.5,
                "coverage": 0.8889,
                "categories": {"value": {"z": 1.2, "percentile": 90.0, "weight": 0.2}},
            }
        },
    }
    data = _data()

    payload = stock_payload(data, "600001", scoring_v2=snapshot)
    missing = stock_payload(data, "600002", scoring_v2=snapshot)

    v2 = payload["scoring_v2"]
    assert v2["score"] == 87.5 and v2["coverage"] == 0.8889
    assert v2["counted"] is False and v2["stale"] is True
    assert v2["inverted"] == ["roe", "vol_60d"]
    assert payload["baseline"]["total"] == 75.0
    assert missing["scoring_v2"]["score"] is None
    assert stock_payload(data, "600001")["scoring_v2"] is None
