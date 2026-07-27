from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from scripts.run_csi300_post_close import (
    PipelineConfig,
    _processed_stage_attempt,
    _raw_stage_attempt,
    run_pipeline,
)


class RunCsi300PostCloseScriptTest(unittest.TestCase):
    def test_pipeline_runs_explicit_incremental_baseline_stages_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            state = _seed_state(config, date(2026, 1, 2))
            runner = RecordingRunner(config)

            result = run_pipeline(config, runner=runner)

            scripts = [Path(command[0]).name for command, _ in runner.calls]
            self.assertEqual(
                scripts,
                [
                    "fetch_index_universe.py",
                    "collect_historical_prices.py",
                    "build_historical_price_features.py",
                    "collect_historical_prices.py",
                    "build_historical_price_features.py",
                    "fetch_market_state.py",
                    "collect_point_in_time_factors.py",
                    "build_point_in_time_factors.py",
                    "collect_corporate_actions.py",
                    "build_corporate_actions.py",
                    "build_daily_decision_report.py",
                    "run_post_close_daily_cycle.py",
                    "audit_csi300_paper_validation.py",
                ],
            )
            self.assertTrue(
                all("dqn" not in " ".join(command).lower() for command, _ in runner.calls)
            )
            collect_commands = [
                command
                for command, _ in runner.calls
                if Path(command[0]).name.startswith("collect_")
            ]
            price_commands = [
                command
                for command in collect_commands
                if Path(command[0]).name == "collect_historical_prices.py"
            ]
            self.assertEqual(
                [_argument(command, "--adjust") for command in price_commands],
                ["hfq", "none"],
            )
            self.assertTrue(
                all(
                    _argument(command, "--start") == "2026-01-03"
                    for command in collect_commands
                )
            )
            self.assertTrue(all(timeout > 0 for _, timeout in runner.calls))
            paper_command = next(
                command
                for command, _ in runner.calls
                if Path(command[0]).name == "run_post_close_daily_cycle.py"
            )
            self.assertEqual(
                _argument(paper_command, "--evidence-parent"),
                state["validation_anchor"]["path"],
            )
            self.assertEqual(_argument(paper_command, "--slippage-rate"), "0.0005")
            self.assertNotIn("--pnl-curve", paper_command)
            self.assertEqual(
                _argument(paper_command, "--current-universe"),
                str(config.cycle_root / "2026-01-05" / "current_universe.csv"),
            )
            state_after = json.loads(config.state.read_text(encoding="utf-8"))
            self.assertEqual(state_after["last_successful_as_of"], "2026-01-05")
            self.assertEqual(state_after["validation_anchor"], state["validation_anchor"])
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["validation_status"], "COLLECTING")
            self.assertNotEqual(state_after, state)

    def test_pipeline_passes_sibling_pnl_curve_to_paper_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            _seed_state(config, date(2026, 1, 2))
            curve = config.comparison.with_name("pnl_curve.json")
            _write_json(curve, {"schema_version": 1})
            runner = RecordingRunner(config)

            run_pipeline(config, runner=runner)

            paper_command = next(
                command
                for command, _ in runner.calls
                if Path(command[0]).name == "run_post_close_daily_cycle.py"
            )
            self.assertEqual(_argument(paper_command, "--pnl-curve"), str(curve))

    def test_pipeline_rejects_missing_explicit_pnl_curve_before_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = replace(_config(root), pnl_curve=root / "missing-pnl-curve.json")
            _seed_state(config, date(2026, 1, 2))
            runner = RecordingRunner(config)

            with self.assertRaisesRegex(ValueError, "PnL curve does not exist"):
                run_pipeline(config, runner=runner)

            self.assertEqual(runner.calls, [])

    def test_pipeline_rejects_missing_validation_anchor_before_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            _seed_state(config, date(2026, 1, 2), with_validation_anchor=False)
            runner = RecordingRunner(config)

            with self.assertRaisesRegex(ValueError, "validation anchor"):
                run_pipeline(config, runner=runner)

            self.assertEqual(runner.calls, [])

    def test_pipeline_rejects_account_state_date_divergence_before_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            _seed_state(config, date(2026, 1, 2))
            _write_json(
                config.account,
                {"cash": 100000.0, "last_processed_date": "2026-01-03"},
            )
            runner = RecordingRunner(config)

            with self.assertRaisesRegex(ValueError, "account and pipeline state dates differ"):
                run_pipeline(config, runner=runner)

            self.assertEqual(runner.calls, [])

    def test_later_v2_cycle_chains_to_prior_cycle_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            state = _seed_state(config, date(2026, 1, 2))
            prior_cycle = root / "cycles" / "2026-01-02" / "cycle_manifest.json"
            _write_json(
                prior_cycle,
                {
                    "schema_version": 2,
                    "kind": "paper_trading_cycle",
                    "as_of": "2026-01-02",
                },
            )
            state["cycle_manifest"] = {
                "path": str(prior_cycle.resolve()),
                "bytes": prior_cycle.stat().st_size,
                "sha256": hashlib.sha256(prior_cycle.read_bytes()).hexdigest(),
            }
            _write_json(config.state, state)
            runner = RecordingRunner(config)

            run_pipeline(config, runner=runner)

            paper_command = next(
                command
                for command, _ in runner.calls
                if Path(command[0]).name == "run_post_close_daily_cycle.py"
            )
            self.assertEqual(
                _argument(paper_command, "--evidence-parent"),
                str(prior_cycle.resolve()),
            )

    def test_failed_raw_stage_retries_only_failed_scopes_from_immutable_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            state = _seed_state(config, date(2026, 1, 2))
            failed = (
                config.raw_price_root
                / "csi300-signal-price-raw-20260105"
                / "manifest.json"
            )
            _write_manifest(
                failed,
                layer="raw",
                parent=state["manifests"]["signal_price"]["raw_manifest"],
                scopes=[
                    {
                        "symbol": "000001.SZ",
                        "status": "failed",
                        "artifact": None,
                        "error": "provider unavailable",
                    }
                ],
                request={
                    "start": "2026-01-03",
                    "end": "2026-01-05",
                    "adjust": "hfq",
                },
            )
            runner = RecordingRunner(config)

            run_pipeline(config, runner=runner)

            signal_command = next(
                command
                for command, _ in runner.calls
                if Path(command[0]).name == "collect_historical_prices.py"
                and _argument(command, "--adjust") == "hfq"
            )
            self.assertEqual(
                _argument(signal_command, "--run-id"),
                "csi300-signal-price-raw-20260105-retry-1",
            )
            self.assertEqual(
                _argument(signal_command, "--resume-from"),
                str(failed.resolve()),
            )
            self.assertNotIn("--append-from", signal_command)

    def test_all_empty_price_stage_restarts_from_append_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            append_parent = root / "seed" / "manifest.json"
            _write_manifest(append_parent, layer="raw")
            empty = root / "raw" / "prices-20260105" / "manifest.json"
            _write_manifest(
                empty,
                layer="raw",
                parent=str(append_parent.resolve()),
                scopes=[
                    {
                        "symbol": "000001.SZ",
                        "status": "empty",
                        "artifact": "artifact.txt",
                        "error": None,
                    }
                ],
                request={"start": "2026-01-03", "end": "2026-01-05", "adjust": "none"},
                artifact_text="",
            )

            attempt = _raw_stage_attempt(
                root / "raw",
                base_run_id="prices-20260105",
                append_parent=append_parent,
                expected_request={
                    "start": "2026-01-03",
                    "end": "2026-01-05",
                    "adjust": "none",
                },
                require_rows=True,
            )

            self.assertTrue(attempt.needs_run)
            self.assertEqual(attempt.run_id, "prices-20260105-retry-1")
            self.assertEqual(attempt.parent_argument, "--append-from")
            self.assertEqual(attempt.parent_manifest, append_parent)

    def test_processed_factor_retry_rejects_stale_material_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw" / "manifest.json"
            _write_manifest(raw, layer="raw")
            completed = (
                root
                / "processed"
                / "csi300-factor-20260714"
                / "manifest.json"
            )
            raw_sha256 = hashlib.sha256(raw.read_bytes()).hexdigest()
            _write_manifest(
                completed,
                layer="processed",
                parent=str(raw.resolve()),
                request={
                    "parent_manifest_sha256": raw_sha256,
                    "trading_calendar_sha256": "old-calendar",
                    "price_features_sha256": "old-features",
                },
            )

            attempt = _processed_stage_attempt(
                root / "processed",
                base_run_id="csi300-factor-20260714",
                raw_manifest=raw,
                material_sha256={
                    "trading_calendar_sha256": "new-calendar",
                    "price_features_sha256": "new-features",
                },
            )

            self.assertTrue(attempt.needs_run)
            self.assertEqual(
                attempt.run_id,
                "csi300-factor-20260714-retry-1",
            )

    def test_processed_factor_reuses_matching_material_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw" / "manifest.json"
            _write_manifest(raw, layer="raw")
            completed = (
                root
                / "processed"
                / "csi300-factor-20260714"
                / "manifest.json"
            )
            raw_sha256 = hashlib.sha256(raw.read_bytes()).hexdigest()
            _write_manifest(
                completed,
                layer="processed",
                parent=str(raw.resolve()),
                request={
                    "parent_manifest_sha256": raw_sha256,
                    "trading_calendar_sha256": "calendar",
                    "price_features_sha256": "features",
                },
            )

            attempt = _processed_stage_attempt(
                root / "processed",
                base_run_id="csi300-factor-20260714",
                raw_manifest=raw,
                material_sha256={
                    "trading_calendar_sha256": "calendar",
                    "price_features_sha256": "features",
                },
            )

            self.assertFalse(attempt.needs_run)
            self.assertEqual(attempt.run_id, "csi300-factor-20260714")
            self.assertEqual(attempt.manifest, completed.resolve())

    def test_timeout_stops_before_paper_execution_and_preserves_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            _seed_state(config, date(2026, 1, 2))
            state_before = config.state.read_bytes()
            account_before = config.account.read_bytes()
            runner = RecordingRunner(config, timeout_on="collect_point_in_time_factors.py")

            with self.assertRaises(subprocess.TimeoutExpired):
                run_pipeline(config, runner=runner)

            self.assertFalse(
                any(
                    Path(command[0]).name == "run_post_close_daily_cycle.py"
                    for command, _ in runner.calls
                )
            )
            self.assertEqual(config.state.read_bytes(), state_before)
            self.assertEqual(config.account.read_bytes(), account_before)

    def test_audit_failure_preserves_committed_account_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            _seed_state(config, date(2026, 1, 2))
            runner = RecordingRunner(
                config, fail_on="audit_csi300_paper_validation.py"
            )

            with self.assertRaises(subprocess.CalledProcessError):
                run_pipeline(config, runner=runner)

            account = json.loads(config.account.read_text(encoding="utf-8"))
            state = json.loads(config.state.read_text(encoding="utf-8"))
            self.assertEqual(account["last_processed_date"], "2026-01-05")
            self.assertEqual(state["last_successful_as_of"], "2026-01-05")

    def test_same_date_replay_only_reaudits_committed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            _seed_state(config, date(2026, 1, 2))
            run_pipeline(config, runner=RecordingRunner(config))
            account_before = config.account.read_bytes()
            replay_runner = RecordingRunner(config)

            result = run_pipeline(config, runner=replay_runner)

            self.assertEqual(
                [Path(command[0]).name for command, _ in replay_runner.calls],
                ["audit_csi300_paper_validation.py"],
            )
            self.assertEqual(config.account.read_bytes(), account_before)
            self.assertEqual(result["status"], "already_completed")
            self.assertEqual(result["validation_status"], "COLLECTING")

    def test_pipeline_rejects_validation_session_gap_before_paper_commit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = replace(_config(root), as_of=date(2026, 1, 6))
            _seed_state(config, date(2026, 1, 2))
            state_before = config.state.read_bytes()
            account_before = config.account.read_bytes()
            runner = RecordingRunner(
                config,
                benchmark_dates=(date(2026, 1, 5), date(2026, 1, 6)),
            )

            with self.assertRaisesRegex(
                ValueError,
                "validation session continuity",
            ):
                run_pipeline(config, runner=runner)

            self.assertFalse(
                any(
                    Path(command[0]).name == "run_post_close_daily_cycle.py"
                    for command, _ in runner.calls
                )
            )
            self.assertEqual(config.state.read_bytes(), state_before)
            self.assertEqual(config.account.read_bytes(), account_before)

    def test_pipeline_accepts_weekend_between_parent_and_next_session(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            _seed_state(config, date(2026, 1, 2))
            runner = RecordingRunner(
                config,
                benchmark_dates=(date(2026, 1, 5),),
            )

            result = run_pipeline(config, runner=runner)

            self.assertEqual(result["status"], "completed")


class RecordingRunner:
    def __init__(
        self,
        config: PipelineConfig,
        *,
        timeout_on: str | None = None,
        fail_on: str | None = None,
        benchmark_dates: tuple[date, ...] | None = None,
    ) -> None:
        self.config = config
        self.timeout_on = timeout_on
        self.fail_on = fail_on
        self.benchmark_dates = benchmark_dates or (config.as_of,)
        self.calls: list[tuple[list[str], int]] = []

    def __call__(self, command: list[str], *, timeout: int) -> None:
        self.calls.append((list(command), timeout))
        script = Path(command[0]).name
        if script == self.timeout_on:
            raise subprocess.TimeoutExpired(command, timeout)
        if script == self.fail_on:
            raise subprocess.CalledProcessError(1, command)
        if script == "fetch_index_universe.py":
            _write_current_universe(Path(_argument(command, "--output")))
        elif script.startswith("collect_"):
            root = Path(_argument(command, "--raw-root"))
            run_id = _argument(command, "--run-id")
            _write_manifest(
                root / run_id / "manifest.json",
                layer="raw",
                parent=(
                    _optional_argument(command, "--resume-from")
                    or _optional_argument(command, "--append-from")
                ),
            )
        elif script.startswith("build_") and script != "build_daily_decision_report.py":
            root = Path(_argument(command, "--processed-root"))
            run_id = _argument(command, "--run-id")
            raw_manifest = Path(_argument(command, "--raw-manifest"))
            request = {
                "parent_manifest_sha256": hashlib.sha256(
                    raw_manifest.read_bytes()
                ).hexdigest(),
            }
            if script == "build_historical_price_features.py":
                run_dir = root / run_id
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "features.csv").write_text(
                    "trade_date,symbol,close\n2026-01-05,000001.SZ,10\n",
                    encoding="utf-8",
                )
                (run_dir / "daily.csv").write_text(
                    "trade_date,symbol,open,close\n"
                    "2026-01-05,000001.SZ,10,10\n",
                    encoding="utf-8",
                )
            elif script == "build_point_in_time_factors.py":
                trading_calendar = Path(_argument(command, "--trading-calendar"))
                price_features = Path(_argument(command, "--price-features"))
                request.update(
                    {
                        "trading_calendar_sha256": hashlib.sha256(
                            trading_calendar.read_bytes()
                        ).hexdigest(),
                        "price_features_sha256": hashlib.sha256(
                            price_features.read_bytes()
                        ).hexdigest(),
                    }
                )
            elif script == "build_corporate_actions.py":
                run_dir = root / run_id
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "corporate_actions.csv").write_text(
                    "symbol,ex_date,event_type\n",
                    encoding="utf-8",
                )
            _write_manifest(
                root / run_id / "manifest.json",
                layer="processed",
                parent=str(raw_manifest.resolve()),
                request=request,
            )
        elif script == "fetch_market_state.py":
            output = Path(_argument(command, "--output"))
            output.parent.mkdir(parents=True, exist_ok=True)
            rows = [
                "trade_date,index_symbol,index_close,index_ma250,index_below_annual_ma"
            ]
            rows.extend(
                f"{trade_date.isoformat()},sh000300,4000,3900,false"
                for trade_date in self.benchmark_dates
            )
            output.write_text("\n".join(rows) + "\n", encoding="utf-8")
        elif script == "build_daily_decision_report.py":
            _write_json(Path(_argument(command, "--output")), {"scores": [], "risk_warnings": []})
            _write_json(Path(_argument(command, "--data-health-output")), {"passed": True})
        elif script == "run_post_close_daily_cycle.py":
            _write_json(
                Path(_argument(command, "--account")),
                {"cash": 100000.0, "last_processed_date": self.config.as_of.isoformat()},
            )
            _write_json(
                Path(_argument(command, "--cycle-manifest")),
                {"as_of": self.config.as_of.isoformat()},
            )
        elif script == "audit_csi300_paper_validation.py":
            _write_json(
                Path(_argument(command, "--output")),
                {
                    "status": "COLLECTING",
                    "live_trading_authorized": False,
                    "metrics": {"valid_sessions": 1},
                },
            )


def _config(root: Path) -> PipelineConfig:
    membership = root / "membership.csv"
    _write_membership(membership)
    comparison = root / "comparison.json"
    _write_json(comparison, {})
    return PipelineConfig(
        as_of=date(2026, 1, 5),
        state=root / "pipeline_state.json",
        account=root / "account.json",
        membership=membership,
        comparison=comparison,
        raw_price_root=root / "raw_prices",
        processed_price_root=root / "processed_prices",
        raw_factor_root=root / "raw_factors",
        processed_factor_root=root / "processed_factors",
        raw_action_root=root / "raw_actions",
        processed_action_root=root / "processed_actions",
        cycle_root=root / "cycles",
        benchmark_start=date(2020, 6, 1),
        constituent_timeout=60,
        stage_timeout=1800,
        paper_timeout=600,
    )


def _seed_state(
    config: PipelineConfig, as_of: date, *, with_validation_anchor: bool = True
) -> dict[str, object]:
    manifests: dict[str, dict[str, str]] = {}
    for name in ("signal_price", "execution_price", "factor", "corporate_action"):
        raw = config.state.parent / "seed" / name / "raw" / "manifest.json"
        processed = config.state.parent / "seed" / name / "processed" / "manifest.json"
        _write_manifest(raw, layer="raw")
        _write_manifest(processed, layer="processed")
        manifests[name] = {
            "raw_manifest": str(raw.resolve()),
            "raw_manifest_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
            "processed_manifest": str(processed.resolve()),
            "processed_manifest_sha256": hashlib.sha256(processed.read_bytes()).hexdigest(),
        }
    payload = {
        "schema_version": 1,
        "last_successful_as_of": as_of.isoformat(),
        "manifests": manifests,
    }
    if with_validation_anchor:
        anchor = config.state.parent / "validation" / "anchor_manifest.json"
        _write_json(
            anchor,
            {
                "schema_version": 1,
                "kind": "paper_validation_anchor",
                "as_of": as_of.isoformat(),
            },
        )
        payload["validation_anchor"] = {
            "path": str(anchor.resolve()),
            "bytes": anchor.stat().st_size,
            "sha256": hashlib.sha256(anchor.read_bytes()).hexdigest(),
        }
    _write_json(config.state, payload)
    _write_json(
        config.account,
        {
            "cash": 100000.0,
            "positions": {},
            "nav_history": [],
            "pending_targets": {},
            "pending_signal_date": None,
            "last_processed_date": as_of.isoformat(),
        },
    )
    return payload


def _write_membership(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "index_code",
                "symbol",
                "member_from",
                "member_to",
                "source",
                "source_fetched_at",
            ),
        )
        writer.writeheader()
        for value in range(1, 301):
            writer.writerow(
                {
                    "index_code": "000300",
                    "symbol": f"{value:06d}.SZ",
                    "member_from": "2020-01-01",
                    "member_to": "",
                    "source": "fixture",
                    "source_fetched_at": "2026-01-01T00:00:00Z",
                }
            )


def _write_current_universe(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("symbol", "index_code"))
        writer.writeheader()
        for value in range(1, 301):
            writer.writerow({"symbol": f"{value:06d}.SZ", "index_code": "000300"})


def _write_manifest(
    path: Path,
    *,
    layer: str,
    parent: str | None = None,
    scopes: list[dict[str, object]] | None = None,
    request: dict[str, object] | None = None,
    artifact_text: str = "fixture\n",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    artifact = path.parent / "artifact.txt"
    artifact.write_text(artifact_text, encoding="utf-8")
    payload = {
        "run_id": path.parent.name,
        "layer": layer,
        "parent_manifest": parent,
        "request": request or {},
        "scopes": scopes or [],
        "artifacts": [
            {
                "path": artifact.name,
                "bytes": artifact.stat().st_size,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            }
        ],
    }
    _write_json(path, payload)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _argument(command: list[str], name: str) -> str:
    return command[command.index(name) + 1]


def _optional_argument(command: list[str], name: str) -> str | None:
    return _argument(command, name) if name in command else None


if __name__ == "__main__":
    unittest.main()
