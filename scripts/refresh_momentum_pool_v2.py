"""Refresh the shadow momentum pool v2 once per closed CSI 300 session, next to v1.

Run after the counted post-close cycle and the v1 refresh. It reads the same hash-verified data the
cycle committed in the pipeline state and writes only under ``--pool-root``. It never touches the
counted paper account, the pipeline state or evidence files. Rules: ``momentum_pool_v2``.

    python scripts/refresh_momentum_pool_v2.py
    python scripts/refresh_momentum_pool_v2.py --replay-start 2024-01-02   # v1 vs v2 replay
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (SRC, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fintech_quant.data.historical_universe import (  # noqa: E402
    active_symbols,
    load_membership_intervals,
)
from fintech_quant.data.manifest_chain import load_verified_manifest  # noqa: E402
from fintech_quant.execution.paper_evidence import verify_file_reference  # noqa: E402
from fintech_quant.reports.picker import load_picker_data, load_series  # noqa: E402
from fintech_quant.research import momentum_pool as v1  # noqa: E402
from fintech_quant.research import momentum_pool_v2 as v2  # noqa: E402
from fintech_quant.research.momentum_setup import screen  # noqa: E402
from scripts.refresh_momentum_pool import (  # noqa: E402
    _require_safe_output,
    _write_json_atomic,
    _write_once,
)


EXCLUDED_WINDOW = ("2024-09-15", "2024-10-31")


def refresh(state_path: Path, pool_root: Path) -> dict[str, object]:
    _require_safe_output(pool_root)
    data = load_picker_data(state_path)
    state_file = pool_root / "state.json"
    pool = (
        json.loads(state_file.read_text(encoding="utf-8"))
        if state_file.exists()
        else v2.initial_pool_state()
    )
    if pool.get("as_of") == data.as_of:
        return {"status": "already_refreshed", "as_of": data.as_of, **_summary(pool)}
    sessions = sorted(
        {b.trade_date for item in data.series.values() for b in item.bars if b.trade_date < data.as_of}
    )
    updated = v2.step_pool(
        pool,
        as_of=data.as_of,
        series=data.series,
        screen_results=data.screen_results,
        previous_session=sessions[-1] if sessions else None,
    )
    updated["sources"] = data.sources
    snapshot = pool_root / data.as_of / "pool_state.json"
    _write_once(snapshot, updated)
    _write_json_atomic(state_file, updated)
    return {"status": "refreshed", "as_of": data.as_of, "snapshot": str(snapshot), **_summary(updated)}


def replay(state_path: Path, pool_root: Path, start: str) -> dict[str, object]:
    """Replay v1 and v2 on the same daily screens over point-in-time CSI 300 membership."""
    _require_safe_output(pool_root)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    signal = load_verified_manifest(
        Path(state["manifests"]["signal_price"]["processed_manifest"]), expected_layer="processed"
    )
    intervals = load_membership_intervals(verify_file_reference(state["membership"]))
    benchmark = _benchmark(verify_file_reference(state["benchmark"]))
    series = load_series(signal.artifacts["features.csv"])
    end = str(state["last_successful_as_of"])
    sessions = sorted(
        {b.trade_date for item in series.values() for b in item.bars if start <= b.trade_date <= end}
    )
    pool_v1, pool_v2, previous = v1.initial_pool_state(), v2.initial_pool_state(), None
    for session in sessions:
        members = set(active_symbols(intervals, date.fromisoformat(session)))
        results = screen(series, session, members=members)
        pool_v1 = v1.step_pool(
            pool_v1, as_of=session, series=series, screen_results=results, previous_session=previous
        )
        pool_v2 = v2.step_pool(
            pool_v2, as_of=session, series=series, screen_results=results, previous_session=previous
        )
        previous = session
    comparison = compare(pool_v1, pool_v2, benchmark, sessions)
    comparison.update({"start": start, "end": end, "sources": {"signal_price_manifest": str(signal.path)}})
    output = pool_root / f"replay-{start}-{end}"
    _write_json_atomic(output / "v1_pool_state.json", pool_v1)
    _write_json_atomic(output / "v2_pool_state.json", pool_v2)
    _write_json_atomic(output / "comparison.json", comparison)
    return {"status": "replayed", "start": start, "end": end, "output": str(output)}


def compare(
    pool_v1: Mapping[str, object],
    pool_v2: Mapping[str, object],
    benchmark: Mapping[str, float],
    sessions: Sequence[str],
) -> dict[str, object]:
    book = dict(pool_v2["book"])  # type: ignore[arg-type]
    books = {
        "v1": (pool_v1["nav_history"], pool_v1["closed_trades"]),
        "v2": (book["nav_history"], book["closed_trades"]),
    }
    dates = sorted(benchmark)
    first = dates.index(sessions[0])
    index_history = [
        {"trade_date": d, "equity": benchmark[d], "positions_value": benchmark[d]}
        for d in dates[first : dates.index(sessions[-1]) + 1]
    ]
    base = benchmark[dates[first - 1]]
    result: dict[str, object] = {"excluded_window": list(EXCLUDED_WINDOW)}
    for label, exclude in (("full", None), ("excluding_window", EXCLUDED_WINDOW)):
        result[label] = {
            name: v2.performance(history, trades, exclude=exclude)  # type: ignore[arg-type]
            for name, (history, trades) in books.items()
        }
        result[label]["csi300"] = v2.performance(  # type: ignore[index]
            index_history, [], initial_equity=base, exclude=exclude
        )
    result["v2_brake_transitions"] = dict(pool_v2["brake"])["transitions"]  # type: ignore[arg-type]
    result["v2_skipped_entries"] = _count(book["skipped_entries"], "reason")
    result["v1_skipped_entries"] = _count(pool_v1["skipped_entries"], "reason")  # type: ignore[arg-type]
    return result


def _count(rows: Sequence[Mapping[str, object]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row[key])] = counts.get(str(row[key]), 0) + 1
    return dict(sorted(counts.items()))


def _benchmark(path: Path) -> dict[str, float]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["trade_date"]: float(row["index_close"]) for row in csv.DictReader(handle)}


def _summary(pool: Mapping[str, object]) -> dict[str, object]:
    metrics = v2.pool_metrics(pool)
    return {k: metrics[k] for k in ("equity", "total_return", "drawdown", "brake", "positions", "watchlist")}


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the shadow momentum pool v2.")
    parser.add_argument("--state", default="data/paper/csi300_baseline/pipeline_state.json")
    parser.add_argument("--pool-root", default="outputs/momentum_pool_v2")
    parser.add_argument("--replay-start", default=None, help="Replay v1 and v2 from this date.")
    args = parser.parse_args()
    if args.replay_start:
        result = replay(Path(args.state), Path(args.pool_root), args.replay_start)
    else:
        result = refresh(Path(args.state), Path(args.pool_root))
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
