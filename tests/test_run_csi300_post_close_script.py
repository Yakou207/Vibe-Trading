from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.run_csi300_post_close import PipelineConfig, run_pipeline


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
            state_after = json.loads(config.state.read_text(encoding="utf-8"))
            self.assertEqual(state_after["last_successful_as_of"], "2026-01-05")
            self.assertEqual(result["status"], "completed")
            self.assertNotEqual(state_after, state)

    def test_timeout_stops_before_paper_execution_and_preserves_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            _seed_state(config, date(2026, 1, 2))
            state_before = config.state.read_bytes()
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
            self.assertFalse(config.account.exists())


class RecordingRunner:
    def __init__(self, config: PipelineConfig, *, timeout_on: str | None = None) -> None:
        self.config = config
        self.timeout_on = timeout_on
        self.calls: list[tuple[list[str], int]] = []

    def __call__(self, command: list[str], *, timeout: int) -> None:
        self.calls.append((list(command), timeout))
        script = Path(command[0]).name
        if script == self.timeout_on:
            raise subprocess.TimeoutExpired(command, timeout)
        if script == "fetch_index_universe.py":
            _write_current_universe(Path(_argument(command, "--output")))
        elif script.startswith("collect_"):
            root = Path(_argument(command, "--raw-root"))
            run_id = _argument(command, "--run-id")
            _write_manifest(
                root / run_id / "manifest.json",
                layer="raw",
                parent=_optional_argument(command, "--append-from"),
            )
        elif script.startswith("build_") and script != "build_daily_decision_report.py":
            root = Path(_argument(command, "--processed-root"))
            run_id = _argument(command, "--run-id")
            _write_manifest(root / run_id / "manifest.json", layer="processed")
        elif script == "fetch_market_state.py":
            output = Path(_argument(command, "--output"))
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                "trade_date,index_symbol,index_close,index_ma250,index_below_annual_ma\n"
                "2026-01-05,sh000300,4000,3900,false\n",
                encoding="utf-8",
            )
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


def _seed_state(config: PipelineConfig, as_of: date) -> dict[str, object]:
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
    _write_json(config.state, payload)
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


def _write_manifest(path: Path, *, layer: str, parent: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    artifact = path.parent / "artifact.txt"
    artifact.write_text("fixture\n", encoding="utf-8")
    payload = {
        "run_id": path.parent.name,
        "layer": layer,
        "parent_manifest": parent,
        "request": {},
        "scopes": [],
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
