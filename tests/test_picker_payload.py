from __future__ import annotations

from pathlib import Path

import pytest

from fintech_quant.reports.picker import PickerData, picks_payload, resolve_symbol, stock_payload
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
