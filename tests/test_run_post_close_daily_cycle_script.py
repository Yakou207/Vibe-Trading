from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class RunPostCloseDailyCycleScriptTest(unittest.TestCase):
    def test_v2_cycle_records_policy_inputs_parent_and_account_consistency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _write_v2_inputs(Path(tmp))

            completed = _run_v2_cycle(paths)

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            manifest = json.loads(paths["cycle_manifest"].read_text(encoding="utf-8"))
            report = json.loads(paths["paper_report"].read_text(encoding="utf-8"))
            canonical_account = (
                json.dumps(report["account"], ensure_ascii=False, indent=2, sort_keys=True)
                + "\n"
            ).encode("utf-8")
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["kind"], "paper_trading_cycle")
            self.assertEqual(
                manifest["evidence_parent"]["sha256"],
                hashlib.sha256(paths["evidence_parent"].read_bytes()).hexdigest(),
            )
            self.assertEqual(
                manifest["inputs"]["current_universe"]["sha256"],
                hashlib.sha256(paths["current_universe"].read_bytes()).hexdigest(),
            )
            self.assertEqual(
                manifest["inputs"]["benchmark"]["sha256"],
                hashlib.sha256(paths["benchmark"].read_bytes()).hexdigest(),
            )
            self.assertEqual(manifest["policy"]["slippage_rate"], 0.0005)
            self.assertFalse(manifest["policy"]["dqn_exposure_enabled"])
            self.assertEqual(
                manifest["account_after_sha256"],
                hashlib.sha256(canonical_account).hexdigest(),
            )

    def test_v2_cycle_rejects_dqn_without_mutating_account(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _write_v2_inputs(Path(tmp))
            dqn_report = Path(tmp) / "dqn_report.json"
            dqn_report.write_text("{}\n", encoding="utf-8")
            account_before = paths["account"].read_bytes()

            completed = _run_v2_cycle(paths, dqn_report=dqn_report)

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("DQN", completed.stderr)
            self.assertEqual(paths["account"].read_bytes(), account_before)
            self.assertFalse(paths["cycle_manifest"].exists())

    def test_v2_cycle_requires_material_evidence_before_mutating_account(self) -> None:
        for missing in ("corporate_actions", "data_health"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                paths = _write_v2_inputs(Path(tmp))
                account_before = paths["account"].read_bytes()

                completed = _run_v2_cycle(paths, omitted_input=missing)

                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(missing.replace("_", "-"), completed.stderr)
                self.assertEqual(paths["account"].read_bytes(), account_before)
                self.assertFalse(paths["cycle_manifest"].exists())

    def test_v2_replay_rejects_missing_material_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _write_v2_inputs(Path(tmp))
            first = _run_v2_cycle(paths)
            self.assertEqual(first.returncode, 0, msg=first.stderr)
            account_after = paths["account"].read_bytes()
            paths["data_health"].unlink()

            replay = _run_v2_cycle(paths)

            self.assertNotEqual(replay.returncode, 0)
            self.assertIn("artifact is missing", replay.stderr)
            self.assertEqual(paths["account"].read_bytes(), account_after)

    def test_post_close_cycle_leaves_canonical_account_unchanged_when_dashboard_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            research_report = root / "run_report.json"
            features = root / "features.csv"
            comparison = root / "comparison.json"
            account = root / "account.json"
            targets = root / "targets.csv"
            paper_report = root / "paper_report.json"
            dashboard = root / "dashboard.html"
            cycle_manifest = root / "cycle_manifest.json"
            research_report.write_text(
                json.dumps(
                    {
                        "scores": [_score("2026-01-02", "000001.SZ", 82.0, 1.0)],
                        "risk_warnings": [],
                    }
                ),
                encoding="utf-8",
            )
            features.write_text(
                "symbol,trade_date,close,limit_up,limit_down,is_suspended\n"
                "000001.SZ,2026-01-02,10,false,false,false\n",
                encoding="utf-8",
            )
            comparison.write_text("{\n", encoding="utf-8")
            account.write_text(
                json.dumps(
                    {
                        "cash": 100000.0,
                        "positions": {},
                        "nav_history": [],
                        "pending_targets": {},
                        "pending_signal_date": None,
                        "last_processed_date": "2026-01-01",
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            account_before = account.read_bytes()

            completed = _run_cycle(
                research_report=research_report,
                features=features,
                comparison=comparison,
                account=account,
                targets=targets,
                paper_report=paper_report,
                dashboard=dashboard,
                cycle_manifest=cycle_manifest,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(account.read_bytes(), account_before)
            self.assertFalse(targets.exists())
            self.assertFalse(paper_report.exists())
            self.assertFalse(dashboard.exists())
            self.assertFalse(cycle_manifest.exists())

    def test_post_close_cycle_runs_paper_trading_and_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            research_report = root / "run_report.json"
            features = root / "features.csv"
            comparison = root / "comparison.json"
            dqn_report = root / "dqn_report.json"
            walk_forward = root / "walk_forward.json"
            account = root / "account.json"
            targets = root / "targets.csv"
            paper_report = root / "paper_report.json"
            dashboard = root / "dashboard.html"
            cycle_manifest = root / "cycle_manifest.json"
            research_report.write_text(
                json.dumps(
                    {
                        "date_range": ["2026-01-01", "2026-01-02"],
                        "scores": [
                            _score("2026-01-02", "000001.SZ", 82.0, 1.0),
                            _score("2026-01-02", "000002.SZ", 78.0, 1.0),
                        ],
                        "risk_warnings": [],
                        "risk_summary": {"total_warnings": 0, "by_rule": {}},
                    }
                ),
                encoding="utf-8",
            )
            features.write_text(
                "symbol,trade_date,close,limit_up,limit_down,is_suspended\n"
                "000001.SZ,2026-01-02,10,false,false,false\n"
                "000002.SZ,2026-01-02,20,false,false,false\n",
                encoding="utf-8",
            )
            comparison.write_text(
                json.dumps(
                    {
                        "candidate": {"name": "dqn", "total_return": 0.02},
                        "baseline": {"name": "baseline", "total_return": 0.01},
                        "candidate_vs_benchmark": {
                            "csi300": {"excess_return": 0.015, "tracking_max_drawdown": 0.03}
                        },
                    }
                ),
                encoding="utf-8",
            )
            dqn_report.write_text(
                json.dumps(
                    {
                        "strategy_config": {"symbols": ["000001.SZ", "000002.SZ"]},
                        "trades": [
                            {
                                "trade_date": "2026-01-01",
                                "symbol": "000001.SZ",
                                "action": "buy",
                                "position": 1,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            walk_forward.write_text(
                json.dumps({"summary": {"window_count": 1, "mean_total_return": 0.02}}),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_post_close_daily_cycle.py",
                    "--as-of",
                    "2026-01-02",
                    "--research-report",
                    str(research_report),
                    "--features",
                    str(features),
                    "--comparison",
                    str(comparison),
                    "--dqn-report",
                    str(dqn_report),
                    "--walk-forward",
                    str(walk_forward),
                    "--account",
                    str(account),
                    "--targets-output",
                    str(targets),
                    "--paper-report",
                    str(paper_report),
                    "--dashboard-output",
                    str(dashboard),
                    "--cycle-manifest",
                    str(cycle_manifest),
                    "--buy-threshold",
                    "70",
                    "--min-score-confidence",
                    "0.8",
                    "--max-position-weight",
                    "0.10",
                    "--initial-cash",
                    "100000",
                    "--commission-rate",
                    "0",
                    "--minimum-commission",
                    "0",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            with targets.open(encoding="utf-8", newline="") as handle:
                target_rows = list(csv.DictReader(handle))
            paper_payload = json.loads(paper_report.read_text(encoding="utf-8"))
            cycle_payload = json.loads(cycle_manifest.read_text(encoding="utf-8"))
            account_sha256 = hashlib.sha256(account.read_bytes()).hexdigest()
            dashboard_html = dashboard.read_text(encoding="utf-8")

            second = subprocess.run(
                completed.args,
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertIn("paper_report_path=", completed.stdout)
        self.assertIn("dashboard_path=", completed.stdout)
        self.assertEqual(
            [(row["symbol"], row["target_weight"], row["rl_action"]) for row in target_rows],
            [("000001.SZ", "0.1", "buy"), ("000002.SZ", "0.05", "hold")],
        )
        self.assertEqual(paper_payload["nav"]["equity"], 100000.0)
        self.assertEqual(cycle_payload["as_of"], "2026-01-02")
        self.assertEqual(
            cycle_payload["account_after_sha256"],
            account_sha256,
        )
        self.assertIn("Daily Quant Monitor", dashboard_html)
        self.assertIn("Paper NAV", dashboard_html)
        self.assertIn("0.015000", dashboard_html)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertIn("already_completed=true", second.stdout)


def _run_cycle(
    *,
    research_report: Path,
    features: Path,
    comparison: Path,
    account: Path,
    targets: Path,
    paper_report: Path,
    dashboard: Path,
    cycle_manifest: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/run_post_close_daily_cycle.py",
            "--as-of",
            "2026-01-02",
            "--research-report",
            str(research_report),
            "--features",
            str(features),
            "--comparison",
            str(comparison),
            "--account",
            str(account),
            "--targets-output",
            str(targets),
            "--paper-report",
            str(paper_report),
            "--dashboard-output",
            str(dashboard),
            "--cycle-manifest",
            str(cycle_manifest),
            "--initial-cash",
            "100000",
            "--commission-rate",
            "0",
            "--minimum-commission",
            "0",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )


def _score(trade_date: str, symbol: str, total: float, confidence: float) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "symbol": symbol,
        "total": total,
        "confidence": confidence,
        "missing_fields": [],
    }


def _write_v2_inputs(root: Path) -> dict[str, Path]:
    paths = {
        name: root / filename
        for name, filename in {
            "research_report": "run_report.json",
            "features": "features.csv",
            "comparison": "comparison.json",
            "current_universe": "current_universe.csv",
            "benchmark": "benchmark.csv",
            "corporate_actions": "corporate_actions.csv",
            "data_health": "data_health.json",
            "evidence_parent": "anchor_manifest.json",
            "account": "account.json",
            "targets": "targets.csv",
            "paper_report": "paper_report.json",
            "dashboard": "dashboard.html",
            "cycle_manifest": "cycle_manifest.json",
        }.items()
    }
    paths["research_report"].write_text(
        json.dumps(
            {
                "date_range": ["2026-01-01", "2026-01-02"],
                "scores": [_score("2026-01-02", "000001.SZ", 82.0, 1.0)],
                "risk_warnings": [],
                "risk_summary": {"total_warnings": 0, "by_rule": {}},
            }
        ),
        encoding="utf-8",
    )
    paths["features"].write_text(
        "symbol,trade_date,open,close,limit_up,limit_down,is_suspended\n"
        "000001.SZ,2026-01-02,10,10,false,false,false\n",
        encoding="utf-8",
    )
    paths["comparison"].write_text(
        json.dumps(
            {
                "candidate": {"name": "baseline", "total_return": 0.01},
                "baseline": {"name": "baseline", "total_return": 0.01},
                "candidate_vs_benchmark": {
                    "csi300": {"excess_return": 0.005, "tracking_max_drawdown": 0.02}
                },
            }
        ),
        encoding="utf-8",
    )
    paths["current_universe"].write_text(
        "symbol,name\n000001.SZ,Ping An Bank\n", encoding="utf-8"
    )
    paths["benchmark"].write_text(
        "trade_date,close\n2026-01-02,4000\n", encoding="utf-8"
    )
    paths["corporate_actions"].write_text(
        "symbol,ex_date,action_type,cash_dividend_per_share,share_multiplier,source\n"
        "000001.SZ,2026-01-01,distribution,0.1,1.0,fixture\n",
        encoding="utf-8",
    )
    paths["data_health"].write_text(
        json.dumps({"passed": True}), encoding="utf-8"
    )
    paths["evidence_parent"].write_text(
        json.dumps({"kind": "paper_validation_anchor"}), encoding="utf-8"
    )
    paths["account"].write_text(
        json.dumps(
            {
                "cash": 100000.0,
                "positions": {},
                "nav_history": [],
                "pending_targets": {},
                "pending_signal_date": None,
                "last_processed_date": "2026-01-01",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return paths


def _run_v2_cycle(
    paths: dict[str, Path],
    *,
    dqn_report: Path | None = None,
    omitted_input: str | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "scripts/run_post_close_daily_cycle.py",
        "--as-of",
        "2026-01-02",
        "--research-report",
        str(paths["research_report"]),
        "--features",
        str(paths["features"]),
        "--comparison",
        str(paths["comparison"]),
        "--current-universe",
        str(paths["current_universe"]),
        "--benchmark",
        str(paths["benchmark"]),
        "--evidence-parent",
        str(paths["evidence_parent"]),
        "--account",
        str(paths["account"]),
        "--targets-output",
        str(paths["targets"]),
        "--paper-report",
        str(paths["paper_report"]),
        "--dashboard-output",
        str(paths["dashboard"]),
        "--cycle-manifest",
        str(paths["cycle_manifest"]),
    ]
    if omitted_input != "corporate_actions":
        command.extend(["--corporate-actions", str(paths["corporate_actions"])])
    if omitted_input != "data_health":
        command.extend(["--data-health", str(paths["data_health"])])
    if dqn_report is not None:
        command.extend(["--dqn-report", str(dqn_report)])
    return subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )


if __name__ == "__main__":
    unittest.main()
