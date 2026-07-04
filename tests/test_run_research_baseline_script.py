from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class RunResearchBaselineScriptTest(unittest.TestCase):
    def test_run_research_baseline_script_writes_report_from_offline_fixtures(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _write_fixture_inputs(root)
            output_root = root / "outputs"

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_research_baseline.py",
                    "--run-id",
                    "fixture-run",
                    "--features",
                    str(paths["features"]),
                    "--universe",
                    str(paths["universe"]),
                    "--fundamentals",
                    str(paths["fundamentals"]),
                    "--capital-flow",
                    str(paths["capital_flow"]),
                    "--output-root",
                    str(output_root),
                    "--initial-cash",
                    "100000",
                    "--buy-threshold",
                    "65",
                    "--min-score-confidence",
                    "0.75",
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            report_path = output_root / "fixture-run" / "run_report.json"
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn(f"report_path={report_path}", result.stdout)
            payload = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["run_id"], "fixture-run")
        self.assertIn("summary", payload)
        self.assertEqual(payload["strategy_config"]["buy_threshold"], 65.0)
        self.assertEqual(payload["strategy_config"]["min_confidence"], 0.75)
        self.assertGreater(payload["summary"]["trade_count"], 0)
        self.assertIn("points", payload["drawdown"])
        self.assertEqual(payload["drawdown"]["points"][0]["trade_date"], "2026-01-01")
        self.assertIn("rolling_peak", payload["drawdown"]["points"][0])


def _write_fixture_inputs(root: Path) -> dict[str, Path]:
    universe = root / "universe.csv"
    features = root / "features.csv"
    fundamentals = root / "fundamentals.csv"
    capital_flow = root / "capital_flow.csv"
    universe.write_text("symbol,name,sector\n000001,Ping An,Bank\n", encoding="utf-8")
    features.write_text(
        "symbol,trade_date,open,high,low,close,volume,amount,source,return_1d,ma20,ma60,ma250,"
        "close_above_ma20,close_above_ma60,close_above_ma250,rsi14,macd_line,macd_signal,macd_hist,"
        "macd_positive,volatility20\n"
        "000001,2026-01-01,10,10,10,10,1000,10000,fixture,0.01,9,8,7,true,true,true,55,0.1,0.05,0.05,true,0.02\n",
        encoding="utf-8",
    )
    fundamentals.write_text("symbol,pe,pb,roe,growth\n000001,18,1.5,0.16,0.12\n", encoding="utf-8")
    capital_flow.write_text(
        "symbol,trade_date,main_net_inflow,main_outflow_days,margin_financing_positive\n"
        "000001,2026-01-01,1000,0,true\n",
        encoding="utf-8",
    )
    return {
        "universe": universe,
        "features": features,
        "fundamentals": fundamentals,
        "capital_flow": capital_flow,
    }


if __name__ == "__main__":
    unittest.main()
