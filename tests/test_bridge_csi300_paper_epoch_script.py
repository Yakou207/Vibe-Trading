from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from fintech_quant.execution.paper_evidence import file_reference, load_verified_anchor
from scripts.bridge_csi300_paper_epoch import run_bridge
from scripts.run_csi300_post_close import PipelineConfig, run_pipeline
from test_run_csi300_post_close_script import (
    RecordingRunner,
    _argument,
    _config,
    _seed_state,
    _write_json,
    _write_manifest,
)


OLD_DATE = date(2026, 7, 21)
BRIDGE_DATE = date(2026, 10, 16)
NEXT_DATE = date(2026, 10, 19)


class BridgeCsi300PaperEpochScriptTest(unittest.TestCase):
    def test_bridge_creates_superseding_epoch_from_one_data_increment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, formal, validation_root = _bridge_fixture(Path(tmp))
            preserved = _hashes(validation_root, config.cycle_root)
            runner = AdjustAwareRunner(config, benchmark_dates=(OLD_DATE, BRIDGE_DATE))

            result = run_bridge(
                config,
                formal_run_manifest=formal,
                validation_root=validation_root,
                reason="missed sessions while all cash",
                created_at="2026-10-17T00:00:00+00:00",
                runner=runner,
            )

            self.assertEqual(result["cancelled_target_count"], 2)
            collect_commands = [
                command
                for command, _ in runner.calls
                if Path(command[0]).name.startswith("collect_")
            ]
            self.assertEqual(len(collect_commands), 4)
            self.assertTrue(all(_argument(c, "--start") == "2026-07-22" for c in collect_commands))
            self.assertTrue(all(_argument(c, "--end") == "2026-10-16" for c in collect_commands))

            account = json.loads(config.account.read_text(encoding="utf-8"))
            self.assertEqual(account["last_processed_date"], "2026-10-16")
            self.assertEqual(account["pending_targets"], {})
            self.assertIsNone(account["pending_signal_date"])
            self.assertEqual(account["cash"], 100000.0)

            state = json.loads(config.state.read_text(encoding="utf-8"))
            self.assertEqual(state["last_successful_as_of"], "2026-10-16")
            self.assertEqual(state["validation_anchor"], state["evidence_parent"])
            self.assertNotIn("cycle_manifest", state)
            anchor_path = Path(state["validation_anchor"]["path"])
            anchor = load_verified_anchor(anchor_path)
            self.assertEqual(anchor["schema_version"], 2)
            self.assertEqual(anchor["as_of"], "2026-10-16")
            self.assertFalse(anchor["counts_toward_evidence"])
            self.assertEqual(
                set(anchor["supersedes"]),
                {"validation_anchor", "cycle_manifest", "epoch_bridge"},
            )
            self.assertEqual(
                anchor["artifacts"]["account"]["sha256"],
                hashlib.sha256(config.account.read_bytes()).hexdigest(),
            )
            bridge = json.loads(Path(result["bridge_manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(bridge["kind"], "paper_epoch_bridge")
            self.assertFalse(bridge["counts_toward_evidence"])
            self.assertEqual(
                bridge["cancelled_targets"],
                {"signal_date": "2026-07-21", "targets": {"000001.SZ": 0.08, "000002.SZ": 0.08}},
            )
            for path, digest in preserved.items():
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest, path)

    def test_next_session_runs_from_new_anchor_after_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, formal, validation_root = _bridge_fixture(Path(tmp))
            run_bridge(
                config,
                formal_run_manifest=formal,
                validation_root=validation_root,
                reason="missed sessions while all cash",
                runner=AdjustAwareRunner(config, benchmark_dates=(OLD_DATE, BRIDGE_DATE)),
            )
            next_config = replace(config, as_of=NEXT_DATE)

            result = run_pipeline(
                next_config,
                runner=AdjustAwareRunner(next_config, benchmark_dates=(BRIDGE_DATE, NEXT_DATE)),
            )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["validation_status"], "COLLECTING")

    def test_refuses_account_with_positions_without_mutation(self) -> None:
        self._assert_refused_without_mutation(
            lambda account: account.update({"positions": {"000001.SZ": {"shares": 100}}}),
            "empty positions",
        )

    def test_refuses_account_outside_normal_drawdown_regime(self) -> None:
        self._assert_refused_without_mutation(
            lambda account: account["drawdown_control_state"].update({"regime": "reduced"}),
            "normal drawdown regime",
        )

    def test_refuses_failed_bridge_data_health_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, formal, validation_root = _bridge_fixture(Path(tmp))
            before = _hashes(config.account, config.state, validation_root)
            runner = AdjustAwareRunner(
                config, benchmark_dates=(OLD_DATE, BRIDGE_DATE), health_passed=False
            )

            with self.assertRaisesRegex(ValueError, "bridge data health did not pass"):
                run_bridge(
                    config,
                    formal_run_manifest=formal,
                    validation_root=validation_root,
                    reason="gap",
                    runner=runner,
                )

            self.assertEqual(_hashes(config.account, config.state, validation_root), before)

    def test_refuses_bridge_end_that_is_not_latest_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, formal, validation_root = _bridge_fixture(Path(tmp))
            before = _hashes(config.account, config.state, validation_root)
            runner = AdjustAwareRunner(config, benchmark_dates=(OLD_DATE, date(2026, 10, 15)))

            with self.assertRaisesRegex(ValueError, "not the latest CSI 300 session"):
                run_bridge(
                    config,
                    formal_run_manifest=formal,
                    validation_root=validation_root,
                    reason="gap",
                    runner=runner,
                )

            self.assertEqual(_hashes(config.account, config.state, validation_root), before)

    def test_refuses_account_that_differs_from_latest_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, formal, validation_root = _bridge_fixture(Path(tmp))
            account = json.loads(config.account.read_text(encoding="utf-8"))
            account["cash"] = 99999.0
            _write_json(config.account, account)

            with self.assertRaisesRegex(ValueError, "account hash mismatch"):
                run_bridge(
                    config,
                    formal_run_manifest=formal,
                    validation_root=validation_root,
                    reason="gap",
                    runner=AdjustAwareRunner(config, benchmark_dates=(OLD_DATE, BRIDGE_DATE)),
                )
            self.assertFalse(any(validation_root.glob("bridge-*")))

    def _assert_refused_without_mutation(self, mutate, message: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, formal, validation_root = _bridge_fixture(Path(tmp), mutate_account=mutate)
            before = _hashes(config.account, config.state, validation_root)
            runner = AdjustAwareRunner(config, benchmark_dates=(OLD_DATE, BRIDGE_DATE))

            with self.assertRaisesRegex(ValueError, message):
                run_bridge(
                    config,
                    formal_run_manifest=formal,
                    validation_root=validation_root,
                    reason="gap",
                    runner=runner,
                )

            self.assertEqual(runner.calls, [])
            self.assertEqual(_hashes(config.account, config.state, validation_root), before)


class AdjustAwareRunner(RecordingRunner):
    """Adds the price-manifest adjust flag and real benchmark dates the anchor checks need."""

    def __init__(self, config: PipelineConfig, *, health_passed: bool = True, **kwargs) -> None:
        super().__init__(config, **kwargs)
        self.health_passed = health_passed

    def __call__(self, command: list[str], *, timeout: int) -> None:
        super().__call__(command, timeout=timeout)
        script = Path(command[0]).name
        if script == "build_historical_price_features.py":
            manifest = Path(_argument(command, "--processed-root")) / _argument(command, "--run-id")
            manifest = manifest / "manifest.json"
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["request"]["adjust"] = (
                "hfq" if "signal-price" in manifest.parent.name else "none"
            )
            _write_json(manifest, payload)
        elif script == "build_daily_decision_report.py" and not self.health_passed:
            _write_json(Path(_argument(command, "--data-health-output")), {"passed": False})


def _bridge_fixture(root: Path, *, mutate_account=None) -> tuple[PipelineConfig, Path, Path]:
    config = replace(_config(root), as_of=BRIDGE_DATE)
    _seed_state(replace(config, as_of=OLD_DATE), OLD_DATE)
    validation_root = config.state.parent / "validation"
    comparison = validation_root / "benchmark_comparison.json"
    formal = validation_root / "formal_run_manifest.json"
    config = replace(config, comparison=comparison)

    for name in ("signal_price", "execution_price"):
        processed = config.state.parent / "seed" / name / "processed" / "manifest.json"
        _write_manifest(
            processed,
            layer="processed",
            request={"adjust": "hfq" if name == "signal_price" else "none"},
        )
    state = json.loads(config.state.read_text(encoding="utf-8"))
    for name in ("signal_price", "execution_price"):
        item = state["manifests"][name]
        item["processed_manifest_sha256"] = hashlib.sha256(
            Path(item["processed_manifest"]).read_bytes()
        ).hexdigest()

    account = {
        "cash": 100000.0,
        "positions": {},
        "shadow_positions": {},
        "dividend_tax_lots": {},
        "shadow_dividend_tax_lots": {},
        "shadow_cash": 100000.0,
        "nav_history": [{"trade_date": OLD_DATE.isoformat(), "equity": 100000.0}],
        "shadow_nav_history": [{"trade_date": OLD_DATE.isoformat(), "equity": 100000.0}],
        "drawdown_control_state": {"regime": "normal", "actual_peak": 100000.0},
        "pending_targets": {"000001.SZ": 0.08, "000002.SZ": 0.08},
        "pending_signal_date": OLD_DATE.isoformat(),
        "last_processed_date": OLD_DATE.isoformat(),
    }
    if mutate_account is not None:
        mutate_account(account)
    _write_json(config.account, account)

    cycle = config.cycle_root / OLD_DATE.isoformat() / "cycle_manifest.json"
    _write_json(
        cycle,
        {
            "schema_version": 2,
            "kind": "paper_trading_cycle",
            "as_of": OLD_DATE.isoformat(),
            "account_after_sha256": hashlib.sha256(config.account.read_bytes()).hexdigest(),
            "evidence_parent": state["validation_anchor"],
        },
    )
    state["cycle_manifest"] = file_reference(cycle)
    state["evidence_parent"] = file_reference(cycle)
    _write_json(config.state, state)
    return config, formal, validation_root


def _hashes(*roots: Path) -> dict[Path, str]:
    files: list[Path] = []
    for root in roots:
        files.extend(
            [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        )
    return {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}


if __name__ == "__main__":
    unittest.main()
