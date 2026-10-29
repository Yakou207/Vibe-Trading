from __future__ import annotations

import io
import json
import plistlib
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from scripts.run_scheduled_csi300_post_close import (
    SHANGHAI,
    default_config,
    previous_session,
    run_scheduled,
    target_session,
)


# 2026-10-01..07 is a holiday week; 2026-10-09 (Fri) and 2026-10-12 (Mon) trade.
CALENDAR = [date(2026, 9, 30), date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 12)]


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=SHANGHAI)


class TargetSessionTest(unittest.TestCase):
    def test_trading_day_before_ready_time_targets_previous_session(self) -> None:
        self.assertEqual(target_session(_at(date(2026, 10, 9), 16, 29), CALENDAR), date(2026, 10, 8))

    def test_trading_day_after_ready_time_targets_today(self) -> None:
        self.assertEqual(target_session(_at(date(2026, 10, 9), 16, 30), CALENDAR), date(2026, 10, 9))

    def test_weekend_and_holiday_target_last_session(self) -> None:
        self.assertEqual(target_session(_at(date(2026, 10, 10), 17, 30), CALENDAR), date(2026, 10, 9))
        self.assertEqual(target_session(_at(date(2026, 10, 5), 18), CALENDAR), date(2026, 9, 30))

    def test_utc_clock_is_converted_to_shanghai(self) -> None:
        utc_now = datetime.fromisoformat("2026-10-09T09:45:00+00:00")  # 17:45 Shanghai
        self.assertEqual(target_session(utc_now, CALENDAR), date(2026, 10, 9))

    def test_previous_session_skips_holiday(self) -> None:
        self.assertEqual(previous_session(date(2026, 10, 8), CALENDAR), date(2026, 9, 30))


class RunScheduledTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.config = default_config(self.root)
        self.config = replace(self.config, max_attempts=3)
        self.config.state.parent.mkdir(parents=True)
        self.anchor = self.root / "anchor_manifest.json"
        self.anchor.write_text("{}", encoding="utf-8")
        self._write_state(date(2026, 10, 8))
        self.config.account.write_text('{"last_processed_date": "2026-10-08"}', encoding="utf-8")
        self.notifications: list[str] = []
        self.sleeps: list[float] = []
        self.log = io.StringIO()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_state(self, as_of: date) -> None:
        self.config.state.write_text(
            json.dumps(
                {
                    "last_successful_as_of": as_of.isoformat(),
                    "validation_anchor": {"path": str(self.anchor)},
                }
            ),
            encoding="utf-8",
        )

    def _run(self, runner: "FakeRunner", now: datetime, **kwargs: object) -> dict[str, object]:
        return run_scheduled(
            self.config,
            now=now,
            calendar=CALENDAR,
            runner=runner,
            notifier=self.notifications.append,
            sleeper=self.sleeps.append,
            log=self.log,
            **kwargs,
        )

    def _canonical_bytes(self) -> tuple[bytes, bytes]:
        return self.config.account.read_bytes(), self.config.state.read_bytes()

    def test_success_runs_fixed_entrypoint_then_audit(self) -> None:
        runner = FakeRunner(self, post_close_codes=[0], audit_status="COLLECTING")

        result = self._run(runner, _at(date(2026, 10, 9), 17, 30))

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["audit_status"], "COLLECTING")
        self.assertEqual(
            [command[1] for command in runner.calls][:2],  # research refreshes follow the audit
            ["scripts/run_csi300_post_close.py", "scripts/audit_csi300_paper_validation.py"],
        )
        post_close = runner.calls[0]
        self.assertEqual(post_close[post_close.index("--as-of") + 1], "2026-10-09")
        self.assertEqual(
            sorted(arg for arg in post_close if arg.startswith("--")),
            ["--account", "--as-of", "--comparison", "--membership", "--state"],
        )
        audit = runner.calls[1]
        self.assertEqual(audit[audit.index("--anchor") + 1], str(self.anchor))
        self.assertEqual(audit[audit.index("--output") + 1], str(self.config.audit_output))
        joined = " ".join(" ".join(command) for command in runner.calls).lower()
        for forbidden in ("dqn", "broker", "threshold"):
            self.assertNotIn(forbidden, joined)
        self.assertEqual(self.notifications, [])

    def test_non_trading_day_with_current_state_does_nothing(self) -> None:
        self._write_state(date(2026, 10, 9))
        runner = FakeRunner(self, post_close_codes=[])

        result = self._run(runner, _at(date(2026, 10, 10), 17, 30))

        self.assertEqual(result["status"], "up_to_date")
        self.assertEqual(runner.calls, [])
        self.assertEqual(self.notifications, [])

    def test_before_ready_time_does_not_run_today(self) -> None:
        runner = FakeRunner(self, post_close_codes=[])

        result = self._run(runner, _at(date(2026, 10, 9), 15, 5))

        self.assertEqual(result["status"], "up_to_date")
        self.assertEqual(runner.calls, [])

    def test_retries_stale_data_then_succeeds(self) -> None:
        runner = FakeRunner(self, post_close_codes=[1, 1, 0], audit_status="COLLECTING")

        result = self._run(runner, _at(date(2026, 10, 9), 17, 30))

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["attempts"], 3)
        self.assertEqual(self.sleeps, [1800, 1800])
        self.assertEqual(self.notifications, [])

    def test_exhausted_retries_stop_notify_and_leave_canonical_files_unchanged(self) -> None:
        before = self._canonical_bytes()
        runner = FakeRunner(self, post_close_codes=[1, 1, 1])

        result = self._run(runner, _at(date(2026, 10, 9), 17, 30))

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["attempts"], 3)
        self.assertEqual(len(runner.calls), 3)
        self.assertNotIn(
            "scripts/audit_csi300_paper_validation.py", [command[1] for command in runner.calls]
        )
        self.assertEqual(len(self.sleeps), 2)
        self.assertEqual(len(self.notifications), 1)
        self.assertEqual(self._canonical_bytes(), before)

    def test_failure_after_state_mutation_stops_without_retry(self) -> None:
        runner = FakeRunner(self, post_close_codes=[1, 0], mutate_on_failure=True)

        result = self._run(runner, _at(date(2026, 10, 9), 17, 30))

        self.assertEqual(result["status"], "failed_after_commit")
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(self.sleeps, [])
        self.assertEqual(len(self.notifications), 1)

    def test_evidence_gap_blocks_without_running(self) -> None:
        self._write_state(date(2026, 9, 30))
        before = self._canonical_bytes()
        runner = FakeRunner(self, post_close_codes=[0])

        result = self._run(runner, _at(date(2026, 10, 9), 17, 30))

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(runner.calls, [])
        self.assertIn("evidence gap", self.notifications[0])
        self.assertEqual(self._canonical_bytes(), before)

    def test_git_problem_blocks_without_running(self) -> None:
        runner = FakeRunner(self, post_close_codes=[0])

        result = self._run(
            runner, _at(date(2026, 10, 9), 17, 30), git_problem="checkout is dirty"
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(runner.calls, [])
        self.assertEqual(self.notifications, ["checkout is dirty"])

    def test_failed_audit_status_notifies(self) -> None:
        runner = FakeRunner(self, post_close_codes=[0], audit_status="FAILED")

        result = self._run(runner, _at(date(2026, 10, 9), 17, 30))

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["audit_status"], "FAILED")
        self.assertEqual(len(self.notifications), 1)

    def test_audit_process_error_notifies(self) -> None:
        runner = FakeRunner(self, post_close_codes=[0], audit_code=2)

        result = self._run(runner, _at(date(2026, 10, 9), 17, 30))

        self.assertEqual(result["status"], "audit_error")
        self.assertEqual(len(self.notifications), 1)

    def test_accepted_cycle_refreshes_pools_and_v2_after_the_audit(self) -> None:
        runner = FakeRunner(self, post_close_codes=[0])

        result = self._run(runner, _at(date(2026, 10, 9), 17, 30))

        scripts = [call[1] for call in runner.calls]
        self.assertEqual(scripts, [
            "scripts/run_csi300_post_close.py",
            "scripts/audit_csi300_paper_validation.py",
            "scripts/refresh_momentum_pool.py",
            "scripts/refresh_momentum_pool_v2.py",
            "scripts/run_scoring_v2.py",
        ])
        self.assertEqual(set(result["research"].values()), {"refreshed"})
        self.assertEqual(self.notifications, [])

    def test_research_failure_is_notified_but_the_cycle_stays_completed(self) -> None:
        runner = FakeRunner(self, post_close_codes=[0], research_code=1)

        result = self._run(runner, _at(date(2026, 10, 9), 17, 30))

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["valid_sessions"], 4)
        self.assertEqual(set(result["research"].values()), {"failed (exit 1)"})
        self.assertEqual(len(self.notifications), 3)
        self.assertIn("counted evidence is unaffected", self.notifications[0])

    def test_failed_audit_skips_research_refreshes(self) -> None:
        runner = FakeRunner(self, post_close_codes=[0], audit_status="FAILED")

        result = self._run(runner, _at(date(2026, 10, 9), 17, 30))

        self.assertNotIn("research", result)
        self.assertNotIn("scripts/refresh_momentum_pool.py", [call[1] for call in runner.calls])

    def test_up_to_date_run_catches_up_lagging_research_only_once(self) -> None:
        self._write_state(date(2026, 10, 9))
        FakeRunner(self, post_close_codes=[])(  # an accepted audit already exists
            ["python", "scripts/audit_csi300_paper_validation.py"], self.log
        )
        runner = FakeRunner(self, post_close_codes=[])

        first = self._run(runner, _at(date(2026, 10, 9), 18, 30))
        again = self._run(runner, _at(date(2026, 10, 9), 19, 30))

        self.assertEqual(first["status"], "up_to_date")
        self.assertEqual(set(first["research"].values()), {"refreshed"})
        self.assertNotIn("research", again)
        self.assertEqual(len(runner.calls), 3)


class LaunchdPlistTest(unittest.TestCase):
    def test_plist_runs_wrapper_hourly_without_launchd_touching_desktop(self) -> None:
        plist_path = (
            Path(__file__).resolve().parents[1]
            / "deploy/launchd/com.vibetrading.csi300-post-close.plist"
        )
        payload = plistlib.loads(plist_path.read_bytes())

        self.assertEqual(payload["Label"], "com.vibetrading.csi300-post-close")
        self.assertTrue(
            payload["ProgramArguments"][1].endswith("scripts/run_scheduled_csi300_post_close.py")
        )
        self.assertFalse(payload["RunAtLoad"])
        self.assertEqual(payload["StartCalendarInterval"], {"Minute": 30})
        self.assertNotIn("WorkingDirectory", payload)
        for key in ("StandardOutPath", "StandardErrorPath"):
            self.assertNotIn("/Desktop/", payload[key])


RESEARCH_SCRIPTS = {
    "scripts/refresh_momentum_pool.py": lambda root: root / "outputs/momentum_pool/state.json",
    "scripts/refresh_momentum_pool_v2.py": lambda root: root / "outputs/momentum_pool_v2/state.json",
    "scripts/run_scoring_v2.py": lambda root: root / "outputs/research/scoring_v2/latest_scores.json",
}


class FakeRunner:
    def __init__(
        self,
        test: RunScheduledTest,
        *,
        post_close_codes: list[int],
        audit_status: str = "COLLECTING",
        audit_code: int = 0,
        mutate_on_failure: bool = False,
        research_code: int = 0,
    ) -> None:
        self.test = test
        self.research_code = research_code
        self.post_close_codes = list(post_close_codes)
        self.audit_status = audit_status
        self.audit_code = audit_code
        self.mutate_on_failure = mutate_on_failure
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], log: io.StringIO) -> int:
        self.calls.append(command)
        config = self.test.config
        if command[1] == "scripts/audit_csi300_paper_validation.py":
            if self.audit_code == 0:
                config.audit_output.parent.mkdir(parents=True, exist_ok=True)
                config.audit_output.write_text(
                    json.dumps({"status": self.audit_status, "metrics": {"valid_sessions": 4}}),
                    encoding="utf-8",
                )
            return self.audit_code
        if command[1] in RESEARCH_SCRIPTS:
            if self.research_code == 0:
                state = json.loads(config.state.read_text(encoding="utf-8"))
                marker = RESEARCH_SCRIPTS[command[1]](config.root)
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(json.dumps({"as_of": state["last_successful_as_of"]}), encoding="utf-8")
            return self.research_code
        code = self.post_close_codes.pop(0)
        if code == 0 or self.mutate_on_failure:
            as_of = date.fromisoformat(command[command.index("--as-of") + 1])
            self.test._write_state(as_of)
        return code


if __name__ == "__main__":
    unittest.main()
