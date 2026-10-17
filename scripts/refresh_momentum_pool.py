"""Refresh the shadow top-5 momentum-setup pool once per closed CSI 300 session.

Run after the counted post-close cycle (recommended 18:30 Asia/Shanghai on trading days). The pool
uses the same hash-verified data the cycle committed in the pipeline state and writes only under
``--pool-root``. It never touches the counted paper account, the pipeline state or evidence files.

    python scripts/refresh_momentum_pool.py
    python scripts/refresh_momentum_pool.py --replay-start 2024-01-02   # historical replay
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import date
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.data.historical_universe import (  # noqa: E402
    active_symbols,
    load_membership_intervals,
)
from fintech_quant.execution.paper_evidence import verify_file_reference  # noqa: E402
from fintech_quant.reports.picker import load_picker_data, load_series  # noqa: E402
from fintech_quant.research.momentum_pool import (  # noqa: E402
    initial_pool_state,
    pool_metrics,
    step_pool,
)
from fintech_quant.research.momentum_setup import screen  # noqa: E402
from fintech_quant.data.manifest_chain import load_verified_manifest  # noqa: E402


PROTECTED_PARTS = ("cycles", "data/paper", "validation")


def refresh(state_path: Path, pool_root: Path) -> dict[str, object]:
    _require_safe_output(pool_root)
    data = load_picker_data(state_path)
    state_file = pool_root / "state.json"
    pool = (
        json.loads(state_file.read_text(encoding="utf-8"))
        if state_file.exists()
        else initial_pool_state()
    )
    if pool.get("as_of") == data.as_of:
        return {"status": "already_refreshed", "as_of": data.as_of, **pool_metrics(pool)}
    sessions = sorted(
        {
            bar.trade_date
            for item in data.series.values()
            for bar in item.bars
            if bar.trade_date < data.as_of
        }
    )
    updated = step_pool(
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
    return {
        "status": "refreshed",
        "as_of": data.as_of,
        "snapshot": str(snapshot),
        **pool_metrics(updated),
    }


def replay(state_path: Path, pool_root: Path, start: str) -> dict[str, object]:
    """Replay the pool rules day by day on point-in-time CSI 300 membership. Research only."""
    _require_safe_output(pool_root)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    signal = load_verified_manifest(
        Path(state["manifests"]["signal_price"]["processed_manifest"]), expected_layer="processed"
    )
    intervals = load_membership_intervals(verify_file_reference(state["membership"]))
    series = load_series(signal.artifacts["features.csv"])
    end = str(state["last_successful_as_of"])
    sessions = sorted(
        {
            b.trade_date
            for item in series.values()
            for b in item.bars
            if start <= b.trade_date <= end
        }
    )
    pool = initial_pool_state()
    previous = None
    for session in sessions:
        members = set(active_symbols(intervals, date.fromisoformat(session)))
        results = screen(series, session, members=members)
        pool = step_pool(
            pool, as_of=session, series=series, screen_results=results, previous_session=previous
        )
        previous = session
    output = pool_root / f"replay-{start}-{end}" / "pool_state.json"
    _write_json_atomic(output, pool)
    return {
        "status": "replayed",
        "start": start,
        "end": end,
        "output": str(output),
        **pool_metrics(pool),
    }


def _require_safe_output(pool_root: Path) -> None:
    resolved = pool_root.resolve().as_posix()
    if any(f"/{part}" in resolved for part in PROTECTED_PARTS):
        raise ValueError(f"pool output must stay outside evidence directories: {pool_root}")


def _write_once(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise ValueError(f"pool snapshot already exists with different content: {path}")
        return
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        staged.write_text(
            json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the shadow momentum-setup pool.")
    parser.add_argument("--state", default="data/paper/csi300_baseline/pipeline_state.json")
    parser.add_argument("--pool-root", default="outputs/momentum_pool")
    parser.add_argument("--replay-start", default=None, help="Replay from this date instead.")
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
