from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


class RlPolicyEvaluationTest(unittest.TestCase):
    def test_evaluate_buy_and_hold_policy_writes_comparable_report(self) -> None:
        from fintech_quant.training import RlStateSample, evaluate_rl_policy

        report = evaluate_rl_policy(
            [
                RlStateSample("000001.SZ", _date("2026-01-01"), _date("2026-01-02"), ("x",), (1.0,), 0.10),
                RlStateSample("000001.SZ", _date("2026-01-02"), _date("2026-01-03"), ("x",), (2.0,), -0.05),
            ],
            policy="buy_and_hold",
            run_id="rl-buy-hold",
            transaction_cost=0.001,
        )

        self.assertEqual(report["run_id"], "rl-buy-hold")
        self.assertEqual(report["strategy_config"]["policy"], "buy_and_hold")
        self.assertEqual(report["strategy_config"]["symbol"], "000001.SZ")
        self.assertEqual(report["summary"]["trade_count"], 1)
        self.assertEqual(report["summary"]["win_rate"], 0.5)
        self.assertEqual(report["summary"]["win_rate_basis"], "positive_reward_steps")
        self.assertEqual(report["summary"]["win_rate_sample_count"], 2)
        self.assertEqual(
            report["equity_curve"],
            [
                {"trade_date": "2026-01-01", "equity": 1.0},
                {"trade_date": "2026-01-02", "equity": 1.099},
                {"trade_date": "2026-01-03", "equity": 1.04405},
            ],
        )
        self.assertEqual([trade["action"] for trade in report["trades"]], ["buy"])

    def test_evaluation_report_can_be_summarized_by_performance_reporter(self) -> None:
        from fintech_quant.reports import summarize_report
        from fintech_quant.training import RlStateSample, evaluate_rl_policy

        report = evaluate_rl_policy(
            [
                RlStateSample("000001.SZ", _date("2026-01-01"), _date("2026-01-02"), ("x",), (1.0,), 0.10),
                RlStateSample("000001.SZ", _date("2026-01-02"), _date("2026-01-03"), ("x",), (2.0,), -0.05),
            ],
            policy="buy_and_hold",
            run_id="rl-buy-hold",
            transaction_cost=0.001,
        )

        summary = summarize_report(report)

        self.assertEqual(summary.name, "rl-buy-hold")
        self.assertEqual(summary.trade_count, 1)
        self.assertEqual(summary.win_rate, 0.5)
        self.assertEqual(summary.win_rate_basis, "positive_reward_steps")
        self.assertEqual(summary.win_rate_sample_count, 2)
        self.assertEqual(summary.ending_equity, 1.04405)

    def test_evaluate_policy_selects_requested_symbol(self) -> None:
        from fintech_quant.training import RlStateSample, evaluate_rl_policy

        samples = [
            RlStateSample("600000.SH", _date("2026-01-01"), _date("2026-01-02"), ("x",), (1.0,), 0.50),
            RlStateSample("000001.SZ", _date("2026-01-01"), _date("2026-01-02"), ("x",), (1.0,), 0.10),
        ]

        report = evaluate_rl_policy(samples, policy="always_hold", symbol="600000.SH")

        self.assertEqual(report["strategy_config"]["symbol"], "600000.SH")
        self.assertEqual(report["summary"]["ending_equity"], 1.0)

    def test_evaluate_policy_defaults_to_all_symbols_equal_weight(self) -> None:
        from fintech_quant.training import RlStateSample, evaluate_rl_policy

        report = evaluate_rl_policy(
            [
                RlStateSample("000001.SZ", _date("2026-01-01"), _date("2026-01-02"), ("x",), (1.0,), 0.10),
                RlStateSample("600000.SH", _date("2026-01-01"), _date("2026-01-02"), ("x",), (1.0,), -0.10),
            ],
            policy="buy_and_hold",
            run_id="rl-all-symbols",
        )

        self.assertEqual(report["strategy_config"]["symbol"], "ALL")
        self.assertEqual(report["strategy_config"]["symbols"], ["000001.SZ", "600000.SH"])
        self.assertEqual(report["strategy_config"]["symbol_count"], 2)
        self.assertEqual(report["summary"]["ending_equity"], 1.0)
        self.assertEqual(report["summary"]["trade_count"], 2)
        self.assertEqual(report["summary"]["win_rate"], 0.5)
        self.assertEqual(report["summary"]["win_rate_sample_count"], 2)
        self.assertEqual(
            report["equity_curve"],
            [
                {"trade_date": "2026-01-01", "equity": 1.0},
                {"trade_date": "2026-01-02", "equity": 1.0},
            ],
        )

    def test_evaluate_policy_all_symbols_carries_forward_missing_symbol_dates(self) -> None:
        from fintech_quant.training import RlStateSample, evaluate_rl_policy

        report = evaluate_rl_policy(
            [
                RlStateSample("000001.SZ", _date("2026-01-01"), _date("2026-01-02"), ("x",), (1.0,), 0.10),
                RlStateSample("000001.SZ", _date("2026-01-02"), _date("2026-01-03"), ("x",), (1.0,), 0.10),
                RlStateSample("600000.SH", _date("2026-01-01"), _date("2026-01-03"), ("x",), (1.0,), -0.10),
            ],
            policy="buy_and_hold",
            run_id="rl-all-symbols-missing-date",
        )

        self.assertEqual(
            report["equity_curve"],
            [
                {"trade_date": "2026-01-01", "equity": 1.0},
                {"trade_date": "2026-01-02", "equity": 1.05},
                {"trade_date": "2026-01-03", "equity": 1.055},
            ],
        )

    def test_evaluate_policy_rejects_unknown_policy(self) -> None:
        from fintech_quant.training import RlStateSample, evaluate_rl_policy

        with self.assertRaisesRegex(ValueError, "policy"):
            evaluate_rl_policy(
                [RlStateSample("000001.SZ", _date("2026-01-01"), _date("2026-01-02"), ("x",), (1.0,), 0.01)],
                policy="buy_everything",
            )

    def test_evaluate_rl_policy_script_reads_jsonl_and_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "rl_state.jsonl"
            output_path = root / "rl_report.json"
            _write_jsonl(
                input_path,
                [
                    _row("000001.SZ", "2026-01-01", "2026-01-02", 0.10),
                    _row("000001.SZ", "2026-01-02", "2026-01-03", -0.05),
                ],
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/evaluate_rl_policy.py",
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--policy",
                    "buy_and_hold",
                    "--transaction-cost",
                    "0.001",
                    "--run-id",
                    "fixture-rl",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertIn(f"report_path={output_path}", result.stdout)
        self.assertEqual(payload["run_id"], "fixture-rl")
        self.assertEqual(payload["summary"]["ending_equity"], 1.04405)

    def test_evaluate_rl_policy_script_supports_all_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "rl_state.jsonl"
            output_path = root / "rl_report.json"
            _write_jsonl(
                input_path,
                [
                    _row("000001.SZ", "2026-01-01", "2026-01-02", 0.10),
                    _row("600000.SH", "2026-01-01", "2026-01-02", -0.10),
                ],
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/evaluate_rl_policy.py",
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--policy",
                    "buy_and_hold",
                    "--symbol",
                    "ALL",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("symbol=ALL", result.stdout)
        self.assertEqual(payload["strategy_config"]["symbol"], "ALL")
        self.assertEqual(payload["summary"]["ending_equity"], 1.0)


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _row(symbol: str, trade_date: str, next_trade_date: str, forward_return: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "next_trade_date": next_trade_date,
        "state_fields": ["x"],
        "state_vector": [1.0],
        "forward_return_1d": forward_return,
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
