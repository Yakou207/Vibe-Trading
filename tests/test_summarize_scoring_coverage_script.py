from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class SummarizeScoringCoverageScriptTest(unittest.TestCase):
    def test_summarize_scoring_coverage_reports_component_distribution_and_missing_fields(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            features_path = root / "features.csv"
            fundamentals_path = root / "fundamentals.csv"
            capital_flow_path = root / "capital_flow.csv"
            output_path = root / "scoring_coverage.json"

            universe_path.write_text(
                "symbol,name,sector\n000001,平安银行,银行\n000002,万科A,地产\n",
                encoding="utf-8",
            )
            features_path.write_text(
                "symbol,trade_date,open,high,low,close,volume,amount,source,return_1d,ma20,ma60,ma250,"
                "close_above_ma20,close_above_ma60,close_above_ma250,rsi14,macd_line,macd_signal,macd_hist,"
                "macd_positive,volatility20,limit_up_streak\n"
                "000001,2026-01-02,10,10,10,10,1000,10000,fixture,0.01,9,8,7,"
                "true,true,true,55,0.1,0.05,0.05,true,0.02,1\n"
                "000002,2026-01-02,20,20,20,20,0,20000,fixture,-0.02,21,22,23,"
                "false,false,false,,0.0,0.05,-0.05,false,0.03,\n",
                encoding="utf-8",
            )
            fundamentals_path.write_text(
                "symbol,pe,pb,roe,growth\n000001,18,1.5,0.16,0.12\n",
                encoding="utf-8",
            )
            capital_flow_path.write_text(
                "symbol,trade_date,main_net_inflow,main_outflow_days,margin_financing_positive\n"
                "000001,2026-01-02,1000,0,true\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/summarize_scoring_coverage.py",
                    "--features",
                    str(features_path),
                    "--universe",
                    str(universe_path),
                    "--fundamentals",
                    str(fundamentals_path),
                    "--capital-flow",
                    str(capital_flow_path),
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
            self.assertIn(f"coverage_path={output_path}", result.stdout)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["row_count"], 2)
        self.assertEqual(payload["pipeline"], "a_share_daily_factor_pipeline_v0")
        self.assertEqual(payload["score_distribution"]["max"], 95.0)
        self.assertEqual(payload["score_distribution"]["min"], 5.0)
        self.assertEqual(payload["component_summary"]["fundamental"]["max_score"], 35.0)
        self.assertEqual(payload["component_summary"]["fundamental"]["average_score"], 17.5)
        self.assertEqual(payload["component_summary"]["technical"]["max_score"], 25.0)
        self.assertEqual(payload["component_summary"]["capital_flow"]["max_score"], 25.0)
        self.assertEqual(payload["component_summary"]["sentiment"]["max_score"], 15.0)
        self.assertEqual(payload["missing_field_counts"]["pe"], 1)
        self.assertEqual(payload["missing_field_counts"]["rsi"], 1)
        self.assertEqual(payload["missing_field_counts"]["main_net_inflow"], 1)
        self.assertEqual(payload["missing_field_rates"]["pe"], 0.5)
        self.assertEqual(payload["confidence_average"], 0.6333)


if __name__ == "__main__":
    unittest.main()
