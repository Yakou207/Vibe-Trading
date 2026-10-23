"""Scheduled wrapper for the fixed CSI 300 post-close paper cycle.

Intended to be started by launchd every hour; it picks the due session from the
Shanghai clock, so the Mac's own time zone does not matter. It only ever invokes ``scripts/run_csi300_post_close.py`` with the fixed canonical
arguments and then ``scripts/audit_csi300_paper_validation.py``. It never edits
the account, pipeline state or any manifest itself.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import subprocess
import sys
import time as time_module
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Callable, Iterable, TextIO
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")
# A-shares close at 15:00; provider daily bars are normally complete by about 16:00. If they are
# not, the price freshness gate fails closed and the 30-minute retries pick the data up later.
READY_TIME = time(16, 30)
POST_CLOSE_SCRIPT = "scripts/run_csi300_post_close.py"
AUDIT_SCRIPT = "scripts/audit_csi300_paper_validation.py"

Runner = Callable[[list[str], TextIO], int]
Notifier = Callable[[str], None]


@dataclass(frozen=True)
class SchedulerConfig:
    root: Path
    python: Path
    state: Path
    account: Path
    membership: Path
    comparison: Path
    audit_output: Path
    log_dir: Path
    max_attempts: int = 5
    retry_delay_seconds: int = 1800


def default_config(root: Path = ROOT) -> SchedulerConfig:
    return SchedulerConfig(
        root=root,
        python=root / ".venv" / "bin" / "python",
        state=root / "data/paper/csi300_baseline/pipeline_state.json",
        account=root / "data/paper/csi300_baseline/account.json",
        membership=root
        / "data/diagnostics/csi300_official_adjustments/csi300_membership_20210615_20260630.csv",
        comparison=root / "outputs/csi300_research/hfq-formal-20260713/benchmark_comparison.json",
        audit_output=root / "outputs/paper_trading/csi300_baseline/validation_report.json",
        log_dir=root / "outputs/automation/csi300_post_close",
    )


def target_session(now: datetime, calendar: Iterable[date]) -> date | None:
    """Latest trading session whose post-close data window has opened."""
    local = now.astimezone(SHANGHAI)
    today = local.date()
    eligible = [
        day
        for day in calendar
        if day < today or (day == today and local.time() >= READY_TIME)
    ]
    return max(eligible) if eligible else None


def previous_session(day: date, calendar: Iterable[date]) -> date | None:
    earlier = [item for item in calendar if item < day]
    return max(earlier) if earlier else None


def run_scheduled(
    config: SchedulerConfig,
    *,
    now: datetime,
    calendar: Iterable[date],
    runner: Runner,
    notifier: Notifier,
    sleeper: Callable[[float], None],
    log: TextIO,
    git_problem: str | None = None,
) -> dict[str, object]:
    sessions = sorted(set(calendar))
    _log(log, f"wrapper start now={now.isoformat()}")
    if git_problem is not None:
        return _fail(log, notifier, "blocked", git_problem)
    state_date = date.fromisoformat(str(_load_json(config.state)["last_successful_as_of"]))
    target = target_session(now, sessions)
    if target is None or target <= state_date:
        _log(log, f"up to date: state={state_date} target={target}")
        return {"status": "up_to_date", "state_as_of": state_date.isoformat()}
    expected_parent = previous_session(target, sessions)
    if expected_parent != state_date:
        return _fail(
            log,
            notifier,
            "blocked",
            f"evidence gap: state is {state_date} but {target} needs parent session "
            f"{expected_parent}; resolve the gap/epoch manually before automation resumes",
            target=target,
        )

    command = [
        str(config.python),
        POST_CLOSE_SCRIPT,
        "--as-of",
        target.isoformat(),
        "--state",
        str(config.state),
        "--account",
        str(config.account),
        "--membership",
        str(config.membership),
        "--comparison",
        str(config.comparison),
    ]
    for attempt in range(1, config.max_attempts + 1):
        before = _canonical_hashes(config)
        _log(log, f"attempt {attempt}/{config.max_attempts}: {' '.join(command)}")
        returncode = runner(command, log)
        _log(log, f"attempt {attempt} exit={returncode}")
        if returncode == 0:
            break
        if _canonical_hashes(config) != before:
            return _fail(
                log,
                notifier,
                "failed_after_commit",
                f"{target}: post-close exited {returncode} after account/state changed; "
                "not retrying, inspect the cycle",
                target=target,
                attempts=attempt,
            )
        if attempt == config.max_attempts:
            return _fail(
                log,
                notifier,
                "failed",
                f"{target}: post-close failed {attempt} times without mutating "
                "account/state; session not recorded",
                target=target,
                attempts=attempt,
            )
        _log(log, f"no mutation; retrying in {config.retry_delay_seconds}s")
        sleeper(config.retry_delay_seconds)

    anchor = Path(str(_load_json(config.state)["validation_anchor"]["path"]))
    audit_command = [
        str(config.python),
        AUDIT_SCRIPT,
        "--anchor",
        str(anchor),
        "--cycle-root",
        str(config.root / "outputs/paper_trading/csi300_baseline/cycles"),
        "--output",
        str(config.audit_output),
    ]
    _log(log, f"audit: {' '.join(audit_command)}")
    audit_returncode = runner(audit_command, log)
    if audit_returncode != 0:
        return _fail(
            log,
            notifier,
            "audit_error",
            f"{target}: cycle committed but audit exited {audit_returncode}",
            target=target,
            attempts=attempt,
        )
    report = _load_json(config.audit_output)
    audit_status = str(report.get("status"))
    valid_sessions = report.get("metrics", {}).get("valid_sessions")
    result = {
        "status": "completed",
        "target": target.isoformat(),
        "attempts": attempt,
        "audit_status": audit_status,
        "valid_sessions": valid_sessions,
    }
    _log(log, f"completed: {json.dumps(result)}")
    if audit_status == "FAILED":
        notifier(f"{target}: cycle committed but audit is FAILED (valid_sessions={valid_sessions})")
    return result


def _fail(
    log: TextIO,
    notifier: Notifier,
    status: str,
    message: str,
    *,
    target: date | None = None,
    attempts: int = 0,
) -> dict[str, object]:
    _log(log, f"{status}: {message}")
    notifier(message)
    return {
        "status": status,
        "target": target.isoformat() if target else None,
        "attempts": attempts,
        "message": message,
    }


def _canonical_hashes(config: SchedulerConfig) -> tuple[str, str]:
    return (_sha256(config.account), _sha256(config.state))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _log(log: TextIO, message: str) -> None:
    log.write(f"[{datetime.now(SHANGHAI).isoformat(timespec='seconds')}] {message}\n")
    log.flush()


def _subprocess_runner(root: Path) -> Runner:
    def run(command: list[str], log: TextIO) -> int:
        return subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT).returncode

    return run


def _notify(message: str) -> None:
    subprocess.run(
        [
            "/usr/bin/osascript",
            "-e",
            "on run argv",
            "-e",
            "display notification (item 1 of argv) with title (item 2 of argv)",
            "-e",
            "end run",
            message,
            "Vibe-Trading CSI 300",
        ],
        check=False,
    )


def _git_problem(root: Path) -> str | None:
    def git(*args: str) -> str:
        return subprocess.run(
            ["/usr/bin/git", *args], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()

    branch = git("branch", "--show-current")
    if branch != "main":
        return f"checkout is on branch {branch!r}, expected main"
    if git("status", "--porcelain", "--untracked-files=no"):
        return "checkout has uncommitted tracked changes"
    return None


def _load_calendar(attempts: int, delay: float, log: TextIO) -> list[date]:
    import akshare as ak

    for attempt in range(1, attempts + 1):
        try:
            frame = ak.tool_trade_date_hist_sina()
            return [date.fromisoformat(str(value)[:10]) for value in frame["trade_date"]]
        except Exception as error:  # provider errors vary; retry then fail closed
            _log(log, f"trading calendar attempt {attempt} failed: {error!r}")
            if attempt == attempts:
                raise
            time_module.sleep(delay)
    raise AssertionError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args()
    config = default_config()
    config.log_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(SHANGHAI)
    log_path = config.log_dir / f"{now:%Y%m%dT%H%M%S}.log"
    with (config.log_dir / ".lock").open("w") as lock, log_path.open("a") as log:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _log(log, "another scheduled run holds the lock; exiting")
            return 0
        try:
            calendar = _load_calendar(3, 60, log)
            result = run_scheduled(
                config,
                now=now,
                calendar=calendar,
                runner=_subprocess_runner(config.root),
                notifier=_notify,
                sleeper=time_module.sleep,
                log=log,
                git_problem=_git_problem(config.root),
            )
        except Exception as error:
            _log(log, f"wrapper error: {error!r}")
            _notify(f"scheduled post-close wrapper error: {error}")
            result = {"status": "error", "message": repr(error)}
        if result["status"] == "up_to_date":  # hourly no-op fires keep only the runs.jsonl line
            log_path.unlink(missing_ok=True)
        result = {"started_at": now.isoformat(), "log": str(log_path), **result}
        with (config.log_dir / "runs.jsonl").open("a") as runs:
            runs.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0 if result["status"] in {"completed", "up_to_date"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
