from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


class DqnTrainingTest(unittest.TestCase):
    def test_train_linear_dqn_policy_report_learns_comparable_buy_sell_policy(self) -> None:
        from fintech_quant.training import RlStateSample, train_linear_dqn_policy_report

        samples = [
            RlStateSample("000001.SZ", _date("2026-01-01"), _date("2026-01-02"), ("signal",), (1.0,), 0.10),
            RlStateSample("000001.SZ", _date("2026-01-02"), _date("2026-01-03"), ("signal",), (-1.0,), -0.10),
            RlStateSample("000001.SZ", _date("2026-01-03"), _date("2026-01-04"), ("signal",), (1.0,), 0.05),
        ]

        report = train_linear_dqn_policy_report(
            samples,
            run_id="fixture-dqn",
            symbol="000001.SZ",
            epochs=80,
            learning_rate=0.05,
            gamma=0.0,
            transaction_cost=0.0,
        )

        self.assertEqual(report["run_id"], "fixture-dqn")
        self.assertEqual(report["strategy_config"]["policy"], "linear_q_dqn_v0")
        self.assertEqual(report["strategy_config"]["symbol"], "000001.SZ")
        self.assertEqual(report["summary"]["ending_equity"], 1.155)
        self.assertEqual([trade["action"] for trade in report["trades"]], ["buy", "sell", "buy"])
        self.assertIn("weights", report["model"])

    def test_train_linear_dqn_policy_report_can_evaluate_out_of_sample_after_date(self) -> None:
        from fintech_quant.training import RlStateSample, train_linear_dqn_policy_report

        samples = [
            RlStateSample("000001.SZ", _date("2026-01-01"), _date("2026-01-02"), ("signal",), (1.0,), 0.10),
            RlStateSample("000001.SZ", _date("2026-01-02"), _date("2026-01-03"), ("signal",), (-1.0,), -0.10),
            RlStateSample("000001.SZ", _date("2026-01-03"), _date("2026-01-04"), ("signal",), (1.0,), 0.05),
            RlStateSample("000001.SZ", _date("2026-01-04"), _date("2026-01-05"), ("signal",), (-1.0,), -0.20),
        ]

        report = train_linear_dqn_policy_report(
            samples,
            run_id="fixture-dqn-oos",
            symbol="000001.SZ",
            epochs=80,
            learning_rate=0.05,
            gamma=0.0,
            transaction_cost=0.0,
            eval_start=_date("2026-01-04"),
        )

        self.assertEqual(report["strategy_config"]["eval_start"], "2026-01-04")
        self.assertEqual(report["strategy_config"]["train_sample_count"], 3)
        self.assertEqual(report["strategy_config"]["eval_sample_count"], 1)
        self.assertEqual(report["equity_curve"][0]["trade_date"], "2026-01-04")
        self.assertEqual(report["summary"]["ending_equity"], 1.0)
        self.assertEqual(report["summary"]["trade_count"], 0)

    def test_train_dqn_policy_script_reads_jsonl_and_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "rl_state.jsonl"
            output_path = root / "dqn_report.json"
            _write_jsonl(
                input_path,
                [
                    _row("000001.SZ", "2026-01-01", "2026-01-02", 1.0, 0.10),
                    _row("000001.SZ", "2026-01-02", "2026-01-03", -1.0, -0.10),
                    _row("000001.SZ", "2026-01-03", "2026-01-04", 1.0, 0.05),
                ],
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/train_dqn_policy.py",
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--symbol",
                    "000001.SZ",
                    "--epochs",
                    "80",
                    "--learning-rate",
                    "0.05",
                    "--gamma",
                    "0",
                    "--run-id",
                    "fixture-dqn",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(f"report_path={output_path}", result.stdout)
        self.assertEqual(payload["strategy_config"]["policy"], "linear_q_dqn_v0")
        self.assertEqual(payload["summary"]["ending_equity"], 1.155)

    def test_train_dqn_policy_script_supports_out_of_sample_eval_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "rl_state.jsonl"
            output_path = root / "dqn_report.json"
            _write_jsonl(
                input_path,
                [
                    _row("000001.SZ", "2026-01-01", "2026-01-02", 1.0, 0.10),
                    _row("000001.SZ", "2026-01-02", "2026-01-03", -1.0, -0.10),
                    _row("000001.SZ", "2026-01-03", "2026-01-04", 1.0, 0.05),
                    _row("000001.SZ", "2026-01-04", "2026-01-05", -1.0, -0.20),
                ],
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/train_dqn_policy.py",
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--symbol",
                    "000001.SZ",
                    "--epochs",
                    "80",
                    "--learning-rate",
                    "0.05",
                    "--gamma",
                    "0",
                    "--eval-start",
                    "2026-01-04",
                    "--run-id",
                    "fixture-dqn-oos",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("eval_start=2026-01-04", result.stdout)
        self.assertEqual(payload["strategy_config"]["eval_sample_count"], 1)
        self.assertEqual(payload["equity_curve"][0]["trade_date"], "2026-01-04")


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _row(
    symbol: str,
    trade_date: str,
    next_trade_date: str,
    signal: float,
    forward_return: float,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "next_trade_date": next_trade_date,
        "state_fields": ["signal"],
        "state_vector": [signal],
        "forward_return_1d": forward_return,
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
