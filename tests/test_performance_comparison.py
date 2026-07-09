from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class PerformanceComparisonTest(unittest.TestCase):
    def test_compare_strategy_reports_outputs_core_metrics_and_excess_return(self) -> None:
        from fintech_quant.reports import compare_strategy_reports

        baseline = _report("baseline", [100.0, 102.0, 101.0, 104.0])
        candidate = _report("dqn", [100.0, 103.0, 105.0, 108.0], trade_count=3, win_rate=0.67)

        comparison = compare_strategy_reports(baseline, candidate, walk_forward_segments=2)

        self.assertEqual(comparison.baseline.name, "baseline")
        self.assertEqual(comparison.candidate.name, "dqn")
        self.assertAlmostEqual(comparison.baseline.total_return, 0.04)
        self.assertAlmostEqual(comparison.candidate.total_return, 0.08)
        self.assertAlmostEqual(comparison.excess_return, 0.04)
        self.assertGreater(comparison.candidate.annualized_return, comparison.baseline.annualized_return)
        self.assertGreater(comparison.candidate.sharpe, 0.0)
        self.assertEqual(comparison.candidate.trade_count, 3)
        self.assertEqual(comparison.candidate.win_rate, 0.67)
        self.assertEqual(comparison.candidate.win_rate_basis, "reported_win_rate")
        self.assertIsNone(comparison.candidate.win_rate_sample_count)
        self.assertEqual(len(comparison.walk_forward), 2)
        self.assertEqual(comparison.walk_forward[0]["segment"], 1)
        self.assertIn("candidate_return", comparison.walk_forward[0])
        self.assertIn("excess_return", comparison.walk_forward[0])

    def test_compare_strategy_reports_outputs_benchmark_relative_metrics(self) -> None:
        from fintech_quant.reports import compare_strategy_reports

        baseline = _report("baseline", [100.0, 102.0, 101.0, 104.0])
        candidate = _report("dqn", [100.0, 103.0, 105.0, 108.0], trade_count=3, win_rate=0.67)
        benchmark = _benchmark([100.0, 101.0, 99.0, 102.0])

        comparison = compare_strategy_reports(
            baseline,
            candidate,
            walk_forward_segments=2,
            benchmark_curves={"sse": benchmark},
        )

        self.assertAlmostEqual(comparison.benchmarks["sse"].total_return, 0.02)
        self.assertAlmostEqual(comparison.candidate_vs_benchmark["sse"]["excess_return"], 0.06)
        self.assertIn("tracking_max_drawdown", comparison.candidate_vs_benchmark["sse"])
        self.assertIn("candidate_benchmark_excess_return", comparison.walk_forward[0])
        self.assertAlmostEqual(comparison.walk_forward[0]["benchmark_return"], -0.01)
        self.assertAlmostEqual(comparison.walk_forward[0]["candidate_benchmark_excess_return"], 0.06)

    def test_compare_strategy_reports_rejects_mismatched_equity_dates(self) -> None:
        from fintech_quant.reports import compare_strategy_reports

        baseline = _report("baseline", [100.0, 101.0])
        candidate = _report("dqn", [100.0, 101.0], dates=("2026-01-01", "2026-01-03"))

        with self.assertRaises(ValueError):
            compare_strategy_reports(baseline, candidate)

    def test_compare_strategy_reports_can_align_baseline_to_candidate_dates(self) -> None:
        from fintech_quant.reports import compare_strategy_reports

        baseline = _report("baseline", [100.0, 102.0, 104.0, 106.0])
        baseline["trades"] = [
            {"trade_date": "2026-01-03", "symbol": "000001", "action": "SELL", "realized_pnl": 1.0}
        ]
        candidate = _report(
            "dqn",
            [100.0, 105.0],
            dates=("2026-01-03", "2026-01-04"),
            trade_count=1,
            win_rate=1.0,
        )

        comparison = compare_strategy_reports(baseline, candidate, align_to_candidate=True)

        self.assertEqual(comparison.baseline.name, "baseline")
        self.assertEqual(comparison.baseline.initial_equity, 104.0)
        self.assertEqual(comparison.baseline.ending_equity, 106.0)
        self.assertAlmostEqual(comparison.baseline.total_return, 0.019231)
        self.assertEqual(comparison.candidate.initial_equity, 100.0)
        self.assertEqual(comparison.candidate.ending_equity, 105.0)
        self.assertAlmostEqual(comparison.excess_return, 0.030769)
        self.assertEqual(comparison.walk_forward[0]["start_date"], "2026-01-03")

    def test_compare_strategy_reports_aligns_baseline_trade_count_to_candidate_dates(self) -> None:
        from fintech_quant.reports import compare_strategy_reports

        baseline = _report("baseline", [100.0, 102.0, 104.0, 106.0], trade_count=3, win_rate=0.67)
        baseline["trades"] = [
            {"trade_date": "2026-01-01", "symbol": "000001", "action": "BUY"},
            {"trade_date": "2026-01-03", "symbol": "000001", "action": "SELL"},
            {"trade_date": "2026-01-04", "symbol": "000002", "action": "BUY"},
        ]
        candidate = _report(
            "dqn",
            [100.0, 105.0],
            dates=("2026-01-03", "2026-01-04"),
            trade_count=1,
            win_rate=1.0,
        )

        comparison = compare_strategy_reports(baseline, candidate, align_to_candidate=True)

        self.assertEqual(comparison.baseline.trade_count, 2)
        self.assertEqual(comparison.baseline.win_rate, 0.0)

    def test_compare_strategy_reports_recomputes_aligned_baseline_win_rate_from_realized_pnl(self) -> None:
        from fintech_quant.reports import compare_strategy_reports

        baseline = _report("baseline", [100.0, 102.0, 104.0, 106.0], trade_count=3, win_rate=1.0)
        baseline["trades"] = [
            {"trade_date": "2026-01-01", "symbol": "000001", "action": "BUY"},
            {"trade_date": "2026-01-03", "symbol": "000003", "action": "BUY"},
            {"trade_date": "2026-01-03", "symbol": "000001", "action": "SELL", "realized_pnl": 2.0},
            {"trade_date": "2026-01-04", "symbol": "000002", "action": "SELL", "realized_pnl": -1.0},
        ]
        candidate = _report(
            "dqn",
            [100.0, 105.0],
            dates=("2026-01-03", "2026-01-04"),
            trade_count=1,
            win_rate=1.0,
        )

        comparison = compare_strategy_reports(baseline, candidate, align_to_candidate=True)

        self.assertEqual(comparison.baseline.trade_count, 3)
        self.assertEqual(comparison.baseline.win_rate, 0.5)
        self.assertEqual(comparison.baseline.win_rate_basis, "closed_trades_realized_pnl")
        self.assertEqual(comparison.baseline.win_rate_sample_count, 2)

    def test_compare_strategy_reports_requires_baseline_trades_when_aligning(self) -> None:
        from fintech_quant.reports import compare_strategy_reports

        baseline = _report("baseline", [100.0, 102.0, 104.0, 106.0])
        candidate = _report(
            "dqn",
            [100.0, 105.0],
            dates=("2026-01-03", "2026-01-04"),
        )

        with self.assertRaisesRegex(ValueError, "baseline report trades are required"):
            compare_strategy_reports(baseline, candidate, align_to_candidate=True)

    def test_compare_strategy_reports_rejects_missing_trade_statistics(self) -> None:
        from fintech_quant.reports import compare_strategy_reports

        candidate = _report("dqn", [100.0, 101.0])
        del candidate["summary"]["trade_count"]

        with self.assertRaises(ValueError):
            compare_strategy_reports(_report("baseline", [100.0, 101.0]), candidate)

    def test_write_comparison_report_serializes_stable_json(self) -> None:
        from fintech_quant.reports import compare_strategy_reports, write_comparison_report

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "comparison.json"
            comparison = compare_strategy_reports(
                _report("baseline", [100.0, 102.0, 104.0]),
                _report("dqn", [100.0, 101.0, 105.0]),
            )
            write_comparison_report(output_path, comparison)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["baseline"]["name"], "baseline")
        self.assertEqual(payload["candidate"]["name"], "dqn")
        self.assertEqual(payload["baseline"]["win_rate_basis"], "reported_win_rate")
        self.assertIsNone(payload["baseline"]["win_rate_sample_count"])
        self.assertIn("excess_return", payload)
        self.assertIn("walk_forward", payload)

    def test_compare_strategy_reports_script_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_path = root / "baseline.json"
            candidate_path = root / "candidate.json"
            output_path = root / "comparison.json"
            baseline_path.write_text(json.dumps(_report("baseline", [100.0, 102.0, 104.0])), encoding="utf-8")
            candidate_path.write_text(json.dumps(_report("dqn", [100.0, 103.0, 106.0])), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/compare_strategy_reports.py",
                    "--baseline",
                    str(baseline_path),
                    "--candidate",
                    str(candidate_path),
                    "--output",
                    str(output_path),
                ],
                cwd=Path(__file__).resolve().parents[1],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertIn("comparison_path=", completed.stdout)
        self.assertEqual(payload["candidate"]["name"], "dqn")
        self.assertGreater(payload["excess_return"], 0.0)

    def test_compare_strategy_reports_script_can_align_to_candidate_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_path = root / "baseline.json"
            candidate_path = root / "candidate.json"
            output_path = root / "comparison.json"
            baseline = _report("baseline", [100.0, 102.0, 104.0, 106.0])
            baseline["trades"] = [
                {"trade_date": "2026-01-03", "symbol": "000001", "action": "SELL", "realized_pnl": 1.0},
                {"trade_date": "2026-01-04", "symbol": "000002", "action": "SELL", "realized_pnl": -1.0},
            ]
            baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
            candidate_path.write_text(
                json.dumps(_report("dqn", [100.0, 105.0], dates=("2026-01-03", "2026-01-04"))),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/compare_strategy_reports.py",
                    "--baseline",
                    str(baseline_path),
                    "--candidate",
                    str(candidate_path),
                    "--output",
                    str(output_path),
                    "--align-to-candidate",
                ],
                cwd=Path(__file__).resolve().parents[1],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertIn("aligned_to_candidate=True", completed.stdout)
        self.assertAlmostEqual(payload["baseline"]["initial_equity"], 104.0)
        self.assertEqual(payload["baseline"]["trade_count"], 2)
        self.assertEqual(payload["baseline"]["win_rate"], 0.5)
        self.assertEqual(payload["baseline"]["win_rate_basis"], "closed_trades_realized_pnl")
        self.assertEqual(payload["baseline"]["win_rate_sample_count"], 2)
        self.assertAlmostEqual(payload["excess_return"], 0.030769)

    def test_compare_strategy_reports_script_writes_benchmark_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_path = root / "baseline.json"
            candidate_path = root / "candidate.json"
            benchmark_path = root / "sse.csv"
            output_path = root / "comparison.json"
            baseline_path.write_text(json.dumps(_report("baseline", [100.0, 102.0, 104.0])), encoding="utf-8")
            candidate_path.write_text(json.dumps(_report("dqn", [100.0, 103.0, 106.0])), encoding="utf-8")
            benchmark_path.write_text(
                "trade_date,index_close\n2026-01-01,100\n2026-01-02,101\n2026-01-03,102\n",
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/compare_strategy_reports.py",
                    "--baseline",
                    str(baseline_path),
                    "--candidate",
                    str(candidate_path),
                    "--benchmark",
                    f"sse={benchmark_path}",
                    "--output",
                    str(output_path),
                ],
                cwd=Path(__file__).resolve().parents[1],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertIn("benchmark=sse", completed.stdout)
        self.assertIn("sse", payload["benchmarks"])
        self.assertAlmostEqual(payload["candidate_vs_benchmark"]["sse"]["excess_return"], 0.04)
        self.assertIn("tracking_max_drawdown", payload["candidate_vs_benchmark"]["sse"])


def _report(
    run_id: str,
    equity_values: list[float],
    *,
    dates: tuple[str, ...] = ("2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"),
    trade_count: int = 1,
    win_rate: float = 1.0,
) -> dict[str, object]:
    used_dates = dates[: len(equity_values)]
    return {
        "run_id": run_id,
        "equity_curve": [
            {"trade_date": trade_date, "cash": equity, "positions_value": 0.0, "equity": equity}
            for trade_date, equity in zip(used_dates, equity_values, strict=True)
        ],
        "summary": {
            "initial_cash": equity_values[0],
            "ending_equity": equity_values[-1],
            "total_return": round((equity_values[-1] - equity_values[0]) / equity_values[0], 6),
            "trade_count": trade_count,
            "win_rate": win_rate,
        },
    }


def _benchmark(index_closes: list[float]) -> list[dict[str, object]]:
    dates = ("2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04")
    return [
        {"trade_date": trade_date, "index_close": close}
        for trade_date, close in zip(dates, index_closes, strict=True)
    ]


if __name__ == "__main__":
    unittest.main()
