from __future__ import annotations

import csv
import json
from pathlib import Path

from fintech_quant.data.run_artifacts import sha256_file
from fintech_quant.research.momentum_setup import screen
from scripts.refresh_momentum_pool import missed_sessions
from test_momentum_setup import _dates
from test_picker_payload import _data


def _state(tmp_path: Path, symbols: list[str]) -> Path:
    membership = tmp_path / "membership.csv"
    with membership.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["index_code", "symbol", "member_from", "member_to"])
        writer.writeheader()
        for symbol in symbols:
            writer.writerow(
                {"index_code": "000300", "symbol": symbol, "member_from": "2000-01-01", "member_to": ""}
            )
    state = tmp_path / "pipeline_state.json"
    reference = {
        "path": str(membership),
        "bytes": membership.stat().st_size,
        "sha256": sha256_file(membership),
    }
    state.write_text(json.dumps({"membership": reference}), encoding="utf-8")
    return state


def test_missed_refreshes_are_caught_up_day_by_day(tmp_path: Path) -> None:
    data = _data()
    days = _dates(200)
    state = _state(tmp_path, sorted(data.members))

    steps = missed_sessions(state, data, pool_as_of=days[-4])

    assert [(session, previous) for session, _, previous in steps] == [
        (days[-3], days[-4]),
        (days[-2], days[-3]),
        (days[-1], days[-2]),
    ]
    assert steps[0][1] == screen(data.series, days[-3], members=set(data.members))
    assert steps[-1][1] == data.screen_results


def test_a_new_pool_starts_at_the_latest_session_only(tmp_path: Path) -> None:
    data = _data()
    days = _dates(200)

    steps = missed_sessions(_state(tmp_path, sorted(data.members)), data, pool_as_of=None)

    assert [(session, previous) for session, _, previous in steps] == [(days[-1], days[-2])]
