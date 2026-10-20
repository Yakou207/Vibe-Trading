"""Exit-lag sensitivity: close-decided exits queued to the next open (opt-in, research only)."""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

import pytest

from fintech_quant.research import momentum_pool as v1
from fintech_quant.research import momentum_pool_v2 as v2
from fintech_quant.research.momentum_setup import Bar, SymbolSeries


DAYS = [(date(2025, 1, 1) + timedelta(days=i)).isoformat() for i in range(36)]
FLAT = (100.0, 101.0, 99.0, 100.0)
# A: trigger on day 30, bought day 31, closes under the 9 EMA on day 32, suspended day 33.
# B: trigger on day 30, bought day 31, trades through its 98 stop on day 32 (intraday exit).
A = [FLAT] * 30 + [
    (100.0, 101.0, 98.0, 100.5),
    (100.2, 100.8, 98.5, 100.4),
    (100.0, 100.3, 99.2, 99.5),
    None,
    (99.0, 99.6, 98.6, 99.3),
    (99.3, 99.8, 98.9, 99.4),
]
B = [FLAT] * 30 + [
    (100.0, 101.0, 98.0, 100.5),
    (100.2, 101.0, 99.0, 100.8),
    (100.6, 101.0, 97.5, 99.0),
    (99.0, 99.5, 98.5, 99.2),
    (99.2, 99.6, 98.8, 99.4),
    (99.4, 99.9, 99.0, 99.6),
]
# sha256 of the default replays below, recorded with the code before the exit-lag option existed.
GOLDEN = {
    "v1": "9c072d66bb685a34f6ba432d7d4bab9bd354ebe915c93cec3fd656f284c2fb49",
    "v2": "cc5185a085aa29d8ef2341001e79409ad02dae87ab23daeb7ccb00bebb9914d1",
}


def _series(symbol: str, ohlc: list[tuple[float, float, float, float] | None]) -> SymbolSeries:
    bars, last = [], 0.0
    for day, row in zip(DAYS, ohlc):
        if row is None:
            bars.append(Bar(day, last, last, last, last, 0.0, suspended=True))
        else:
            bars.append(Bar(day, *row, 1e6))
            last = row[3]
    return SymbolSeries(symbol, bars)


SERIES = {"600001.SH": _series("600001.SH", A), "600002.SH": _series("600002.SH", B)}


def _row(symbol: str, state: str) -> dict[str, object]:
    return {
        "symbol": symbol,
        "state": state,
        "close": 100.5,
        "stop": 98.0,
        "stop_pct": 0.025,
        "confluence": 2,
        "momentum": {"momentum_pct": 0.9},
    }


def _replay(module, **options):  # type: ignore[no-untyped-def]
    state, previous, states = module.initial_pool_state(), DAYS[29], {}
    for day in DAYS[30:]:
        kind = "trigger" if day == DAYS[30] else "setup"
        rows = [_row("600001.SH", kind), _row("600002.SH", kind)]
        state = module.step_pool(
            state,
            as_of=day,
            series=SERIES,
            screen_results=rows,
            previous_session=previous,
            **options,
        )
        states[day] = state
        previous = day
    return states


def _digest(state: dict[str, object]) -> str:
    text = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("name,module", [("v1", v1), ("v2", v2)])
def test_default_path_is_byte_identical_to_pre_option_code(name, module) -> None:  # type: ignore
    final = _replay(module)[DAYS[-1]]
    assert _digest(final) == GOLDEN[name]
    assert _digest(_replay(module, exit_fill="same_close")[DAYS[-1]]) == GOLDEN[name]


@pytest.mark.parametrize("module", [v1, v2])
def test_close_decided_exit_fills_at_the_next_unsuspended_open(module) -> None:  # type: ignore
    states = _replay(module, exit_fill="next_open")

    def book(day: str) -> dict[str, object]:
        return states[day] if module is v1 else states[day]["book"]  # type: ignore[return-value]

    decided = book(DAYS[32])
    assert decided["positions"]["600001.SH"]["exit_pending"] == {
        "reason": "close_below_ema9",
        "decided_on": DAYS[32],
    }
    # The intraday stop exit is unchanged: it still fills at the stop on day 32.
    stop_trade = [t for t in decided["closed_trades"] if t["symbol"] == "600002.SH"]
    assert [(t["reason"], t["exit_date"]) for t in stop_trade] == [("stop", DAYS[32])]
    assert stop_trade[0]["exit_price"] == pytest.approx(98.0 * (1 - v1.SLIPPAGE_RATE))

    # Day 33 is suspended: the position is kept and the exit retried.
    assert "600001.SH" in book(DAYS[33])["positions"]

    final = book(DAYS[34])
    assert "600001.SH" not in final["positions"]
    trade = [t for t in final["closed_trades"] if t["symbol"] == "600001.SH"][0]
    assert trade["reason"] == "close_below_ema9"
    assert trade["decided_on"] == DAYS[32]
    assert trade["exit_date"] == DAYS[34]
    assert trade["exit_price"] == pytest.approx(99.0 * (1 - v1.SLIPPAGE_RATE))


def test_unknown_exit_fill_is_rejected() -> None:
    for module in (v1, v2):
        with pytest.raises(ValueError, match="exit_fill"):
            _replay(module, exit_fill="next_close")
