"""Forward-only intraday trigger monitor for the shadow momentum pool v2 watchlist. Research only.

    python scripts/monitor_momentum_intraday.py plan      # pre-market, after the v2 refresh
    python scripts/monitor_momentum_intraday.py watch     # 09:30-15:00 Asia/Shanghai, polls 1/min
    python scripts/monitor_momentum_intraday.py compare   # rebuild the ledger and the note

``plan`` writes ``<root>/<date>/plan.json`` once (an existing plan with different content is an
error) and rebuilds the ledger. ``watch`` writes ``<root>/<date>/triggers.json`` after every poll
and resumes from it. ``compare`` rebuilds ``ledger.json``, ``comparison.json`` and
``comparison.md`` from the plan/trigger files and the latest pipeline data. Everything stays under
``--root``; the counted paper account, pipeline state, evidence files and pool states are only
read. Rules: ``momentum_intraday``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (SRC, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fintech_quant.reports.live_stock import SHANGHAI, LiveContext, live_intraday  # noqa: E402
from fintech_quant.reports.picker import PickerData, load_picker_data  # noqa: E402
from fintech_quant.research import momentum_intraday as mi  # noqa: E402
from fintech_quant.research.momentum_setup import momentum_table  # noqa: E402
from scripts.refresh_momentum_pool import (  # noqa: E402
    _require_safe_output,
    _write_json_atomic,
    _write_once,
)


def write_plan(
    data: PickerData, pool_v2: Mapping[str, object], root: Path, session_date: str
) -> Path:
    _require_safe_output(root)
    if date.fromisoformat(session_date).weekday() >= 5:
        raise ValueError(f"{session_date} is a weekend")
    if pool_v2.get("as_of") != data.as_of:
        raise ValueError(
            f"pool v2 is at {pool_v2.get('as_of')}, pipeline at {data.as_of}: "
            "run scripts/refresh_momentum_pool_v2.py first"
        )
    plan = mi.build_plan(
        session_date=session_date,
        reference_session=data.as_of,
        watchlist=list(pool_v2["watchlist"]),  # type: ignore[arg-type]
        series=data.series,
        momentum=data.momentum,
        price_ratio=data.price_ratio,
        pool_as_of=pool_v2.get("as_of"),
    )
    plan["sources"] = data.sources
    path = root / session_date / "plan.json"
    _write_once(path, plan)
    return path


def watch(
    root: Path,
    session_date: str,
    context: LiveContext,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(SHANGHAI),
    sleep: Callable[[float], None] = time.sleep,
    once: bool = False,
) -> dict[str, object]:
    _require_safe_output(root)
    if not once and now().date().isoformat() != session_date:
        raise ValueError(f"watch runs only on its own session ({session_date}), forward-only")
    plan_path = root / session_date / "plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    day_path = root / session_date / "triggers.json"
    day = (
        json.loads(day_path.read_text(encoding="utf-8"))
        if day_path.exists()
        else mi.initial_triggers(plan, plan_sha)
    )
    if day["plan_sha256"] != plan_sha:
        raise ValueError(f"{day_path} belongs to a different plan")
    armed = [str(e["symbol"]) for e in plan["names"] if e["armed"]]
    while not day["finalized"]:
        due = None if once else mi.next_poll(now())
        if due is None and not once:
            day = mi.finalize_day(day)
        else:
            if due is not None:
                sleep(max(0.0, (due - now()).total_seconds()))
            minutes: dict[str, Mapping[str, object] | Exception] = {}
            for symbol in armed:
                try:
                    minutes[symbol] = live_intraday(context, symbol)
                except Exception as exc:  # recorded per symbol; the next poll retries
                    minutes[symbol] = exc
            day = mi.apply_poll(
                day, plan, minutes, polled_at=now().isoformat(timespec="seconds")
            )
        _write_json_atomic(day_path, day)
        if once:
            break
    return day


def rebuild(data: PickerData, root: Path) -> dict[str, object]:
    _require_safe_output(root)
    days = []
    for plan_path in sorted(root.glob("*/plan.json")):
        day_path = plan_path.with_name("triggers.json")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        day = json.loads(day_path.read_text(encoding="utf-8")) if day_path.exists() else None
        if day is not None and day["plan_sha256"] != hashlib.sha256(plan_path.read_bytes()).hexdigest():
            raise ValueError(f"{day_path} belongs to a different plan")
        days.append((plan, day))
    members = {s: data.series[s] for s in data.members if s in data.series}
    tables: dict[str, Mapping[str, Mapping[str, float]]] = {}

    def momentum_for(session: str) -> Mapping[str, Mapping[str, float]]:
        if session not in tables:
            tables[session] = momentum_table(members, session)
        return tables[session]

    ledger = mi.build_ledger(days, series=data.series, momentum_for=momentum_for, as_of=data.as_of)
    result = mi.comparison(ledger)
    _write_json_atomic(root / "ledger.json", ledger)
    _write_json_atomic(root / "comparison.json", result)
    (root / "comparison.md").write_text(mi.comparison_markdown(result), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Intraday trigger monitor (research only).")
    parser.add_argument("command", choices=("plan", "watch", "compare"))
    parser.add_argument("--state", type=Path, default=ROOT / "data/paper/csi300_baseline/pipeline_state.json")
    parser.add_argument("--pool-v2-root", type=Path, default=ROOT / "outputs/momentum_pool_v2")
    parser.add_argument("--root", type=Path, default=ROOT / "outputs/momentum_pool_intraday")
    parser.add_argument("--date", default=None, help="Session date (default: today in Shanghai).")
    parser.add_argument("--once", action="store_true", help="watch: poll once now and stop.")
    args = parser.parse_args()
    session_date = args.date or datetime.now(SHANGHAI).date().isoformat()
    if args.command == "watch":
        day = watch(args.root, session_date, LiveContext(cache_dir=None), once=args.once)
        print(f"polls={day['polls']} triggers={len(day['triggers'])} finalized={day['finalized']}")
        return 0
    data = load_picker_data(args.state)
    if args.command == "plan":
        pool_v2 = json.loads((args.pool_v2_root / "state.json").read_text(encoding="utf-8"))
        print(f"plan={write_plan(data, pool_v2, args.root, session_date)}")
    result = rebuild(data, args.root)
    for key in ("as_of", "plan_days", "signals", "intraday_entries", "daily_entries", "both_entered"):
        print(f"{key}={result[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
