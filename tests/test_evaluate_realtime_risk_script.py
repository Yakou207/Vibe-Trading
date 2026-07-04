from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class EvaluateRealtimeRiskScriptTest(unittest.TestCase):
    def test_realtime_risk_script_flags_systemic_drop_count(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quotes_path = root / "quotes.csv"
            output_path = root / "risk.json"
            with quotes_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("symbol", "change_pct", "price", "source"))
                writer.writeheader()
                for index in range(16):
                    writer.writerow(
                        {
                            "symbol": f"0000{index + 1:02d}.SZ",
                            "change_pct": "-0.031",
                            "price": "10.0",
                            "source": "fixture",
                        }
                    )
                writer.writerow({"symbol": "000099.SZ", "change_pct": "-0.03", "price": "9.0", "source": "fixture"})
                writer.writerow({"symbol": "000100.SZ", "change_pct": "", "price": "9.0", "source": "fixture"})
                writer.writerow({"symbol": "600000.SH", "change_pct": "0.01", "price": "8.0", "source": "fixture"})

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/evaluate_realtime_risk.py",
                    "--quotes",
                    str(quotes_path),
                    "--output",
                    str(output_path),
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("risk_action=reduce", result.stdout)
        self.assertIn("valid_quote_rows=18", result.stdout)
        self.assertIn("skipped_quote_rows=1", result.stdout)
        self.assertEqual(payload["risk_input"]["broad_market_drop_gt_3pct_count"], 16)
        self.assertEqual(payload["valid_quote_rows"], 18)
        self.assertEqual(payload["skipped_quote_rows"], 1)
        self.assertEqual(payload["quote_stats"]["drop_threshold"], -0.03)
        self.assertEqual(payload["quote_stats"]["drop_count"], 16)
        self.assertEqual(payload["quote_stats"]["drop_ratio"], round(16 / 18, 6))
        self.assertIn("evaluated_at", payload["metadata"])
        self.assertEqual(payload["action"], "reduce")
        self.assertEqual(payload["warnings"][0]["rule"], "broad_market_drop_gt_3pct_count")

    def test_realtime_risk_script_merges_risk_input_json_with_quote_drop_count(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quotes_path = root / "quotes.csv"
            risk_input_path = root / "risk_input.json"
            output_path = root / "risk.json"
            with quotes_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("symbol", "change_pct", "price", "source"))
                writer.writeheader()
                writer.writerow({"symbol": "000001.SZ", "change_pct": "-0.01", "price": "10.0", "source": "fixture"})
            risk_input_path.write_text(
                json.dumps(
                    {
                        "position_weight": 0.09,
                        "portfolio_drawdown": 0.16,
                        "single_position_drawdown": 0.09,
                        "st_warning": True,
                        "negative_event_count": 1,
                        "goodwill_ratio": 0.31,
                        "pledge_ratio": 0.51,
                        "main_outflow_days": 4,
                        "index_below_annual_ma": True,
                        "broad_market_drop_gt_3pct_count": "ignored because quotes are authoritative",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/evaluate_realtime_risk.py",
                    "--quotes",
                    str(quotes_path),
                    "--risk-input",
                    str(risk_input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        warning_rules = {warning["rule"] for warning in payload["warnings"]}
        self.assertEqual(payload["action"], "liquidate")
        self.assertEqual(payload["risk_input"]["broad_market_drop_gt_3pct_count"], 0)
        self.assertIn("portfolio_drawdown", warning_rules)
        self.assertIn("single_position_drawdown", warning_rules)
        self.assertIn("st_warning", warning_rules)
        self.assertIn("negative_event_count", warning_rules)
        self.assertIn("goodwill_ratio", warning_rules)
        self.assertIn("pledge_ratio", warning_rules)
        self.assertIn("main_outflow_days", warning_rules)
        self.assertIn("index_below_annual_ma", warning_rules)

    def test_realtime_risk_script_uses_custom_limits(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quotes_path = root / "quotes.csv"
            risk_input_path = root / "risk_input.json"
            output_path = root / "risk.json"
            with quotes_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("symbol", "change_pct", "price", "source"))
                writer.writeheader()
                writer.writerow({"symbol": "000001.SZ", "change_pct": "-0.031", "price": "10.0", "source": "fixture"})
            risk_input_path.write_text(
                json.dumps({"portfolio_drawdown": 0.14, "main_outflow_days": 4}, sort_keys=True),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/evaluate_realtime_risk.py",
                    "--quotes",
                    str(quotes_path),
                    "--risk-input",
                    str(risk_input_path),
                    "--output",
                    str(output_path),
                    "--max-portfolio-drawdown",
                    "0.13",
                    "--max-main-outflow-days",
                    "5",
                    "--broad-market-drop-threshold",
                    "0",
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        warning_rules = {warning["rule"] for warning in payload["warnings"]}
        self.assertEqual(payload["limits"]["max_portfolio_drawdown"], 0.13)
        self.assertEqual(payload["limits"]["max_main_outflow_days"], 5)
        self.assertEqual(payload["limits"]["broad_market_drop_threshold"], 0)
        self.assertIn("portfolio_drawdown", warning_rules)
        self.assertIn("broad_market_drop_gt_3pct_count", warning_rules)
        self.assertNotIn("main_outflow_days", warning_rules)

    def test_realtime_risk_script_coerces_risk_input_values(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quotes_path = root / "quotes.csv"
            risk_input_path = root / "risk_input.json"
            output_path = root / "risk.json"
            with quotes_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("symbol", "change_pct", "price", "source"))
                writer.writeheader()
                writer.writerow({"symbol": "000001.SZ", "change_pct": "-0.01", "price": "10.0", "source": "fixture"})
            risk_input_path.write_text(
                json.dumps(
                    {
                        "portfolio_drawdown": "0.16",
                        "st_warning": "false",
                        "main_outflow_days": "4",
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/evaluate_realtime_risk.py",
                    "--quotes",
                    str(quotes_path),
                    "--risk-input",
                    str(risk_input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        warning_rules = {warning["rule"] for warning in payload["warnings"]}
        self.assertEqual(payload["risk_input"]["portfolio_drawdown"], 0.16)
        self.assertIs(payload["risk_input"]["st_warning"], False)
        self.assertEqual(payload["risk_input"]["main_outflow_days"], 4)
        self.assertIn("portfolio_drawdown", warning_rules)
        self.assertIn("main_outflow_days", warning_rules)
        self.assertNotIn("st_warning", warning_rules)

    def test_realtime_risk_script_rejects_invalid_risk_input_value(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quotes_path = root / "quotes.csv"
            risk_input_path = root / "risk_input.json"
            output_path = root / "risk.json"
            with quotes_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("symbol", "change_pct", "price", "source"))
                writer.writeheader()
                writer.writerow({"symbol": "000001.SZ", "change_pct": "-0.01", "price": "10.0", "source": "fixture"})
            risk_input_path.write_text(json.dumps({"st_warning": "maybe"}, sort_keys=True), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/evaluate_realtime_risk.py",
                    "--quotes",
                    str(quotes_path),
                    "--risk-input",
                    str(risk_input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("st_warning", result.stderr)
        self.assertFalse(output_path.exists())

    def test_realtime_risk_script_rejects_fractional_integer_risk_input(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quotes_path = root / "quotes.csv"
            risk_input_path = root / "risk_input.json"
            output_path = root / "risk.json"
            with quotes_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("symbol", "change_pct", "price", "source"))
                writer.writeheader()
                writer.writerow({"symbol": "000001.SZ", "change_pct": "-0.01", "price": "10.0", "source": "fixture"})
            risk_input_path.write_text(json.dumps({"main_outflow_days": 1.5}, sort_keys=True), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/evaluate_realtime_risk.py",
                    "--quotes",
                    str(quotes_path),
                    "--risk-input",
                    str(risk_input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("main_outflow_days", result.stderr)
        self.assertFalse(output_path.exists())

    def test_realtime_risk_script_rejects_invalid_limit(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quotes_path = root / "quotes.csv"
            output_path = root / "risk.json"
            with quotes_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("symbol", "change_pct", "price", "source"))
                writer.writeheader()
                writer.writerow({"symbol": "000001.SZ", "change_pct": "-0.01", "price": "10.0", "source": "fixture"})

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/evaluate_realtime_risk.py",
                    "--quotes",
                    str(quotes_path),
                    "--output",
                    str(output_path),
                    "--max-main-outflow-days",
                    "-1",
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("max_main_outflow_days", result.stderr)
        self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
