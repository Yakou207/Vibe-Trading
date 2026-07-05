from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ExplainStockAnalysisScriptTest(unittest.TestCase):
    def test_explain_stock_analysis_outputs_factor_weights_scores_and_inputs(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            features_path = root / "features.csv"
            fundamentals_path = root / "fundamentals.csv"
            capital_flow_path = root / "capital_flow.csv"
            information_path = root / "information.jsonl"
            output_path = root / "analysis.json"

            universe_path.write_text("symbol,name,sector\n000001,平安银行,银行\n", encoding="utf-8")
            features_path.write_text(
                "symbol,trade_date,open,high,low,close,volume,amount,source,return_1d,return_20d,rs_rank_20d,ma20,ma60,ma250,"
                "close_above_ma20,close_above_ma60,close_above_ma250,rsi14,macd_line,macd_signal,macd_hist,"
                "macd_positive,volatility20,limit_up_streak\n"
                "000001,2026-01-02,10,10,10,10,1000,10000,fixture,0.01,0.12,0.8,9,8,7,"
                "true,true,true,55,0.1,0.05,0.05,true,0.02,1\n",
                encoding="utf-8",
            )
            fundamentals_path.write_text("symbol,pe,pb,roe,growth\n000001,18,1.5,0.16,0.12\n", encoding="utf-8")
            capital_flow_path.write_text(
                "symbol,trade_date,main_net_inflow,main_outflow_days,margin_financing_positive\n"
                "000001,2026-01-02,1000,0,true\n",
                encoding="utf-8",
            )
            information_path.write_text(
                json.dumps(
                    {
                        "symbol": "000001",
                        "sector": None,
                        "published_at": "2026-01-01",
                        "source": "fixture",
                        "category": "market_sentiment",
                        "title": "龙虎榜净买入",
                        "url": "",
                        "summary": "net_amount=1000",
                        "risk_tags": ["dragon_tiger", "dragon_tiger_positive"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/explain_stock_analysis.py",
                    "--features",
                    str(features_path),
                    "--universe",
                    str(universe_path),
                    "--fundamentals",
                    str(fundamentals_path),
                    "--capital-flow",
                    str(capital_flow_path),
                    "--information",
                    str(information_path),
                    "--symbol",
                    "000001",
                    "--trade-date",
                    "2026-01-02",
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
        self.assertIn(f"analysis_path={output_path}", result.stdout)
        self.assertEqual(payload["symbol"], "000001.SZ")
        self.assertEqual(payload["trade_date"], "2026-01-02")
        self.assertEqual(payload["total_score"], 100.0)
        self.assertEqual(payload["components"]["fundamental"]["max_score"], 35.0)
        self.assertEqual(payload["components"]["fundamental"]["weight_pct"], 35.0)
        self.assertEqual(payload["components"]["technical"]["max_score"], 25.0)
        self.assertEqual(payload["components"]["technical"]["weight_pct"], 25.0)
        self.assertEqual(payload["components"]["capital_flow"]["max_score"], 25.0)
        self.assertEqual(payload["components"]["capital_flow"]["weight_pct"], 25.0)
        self.assertEqual(payload["components"]["sentiment"]["max_score"], 15.0)
        self.assertEqual(payload["components"]["sentiment"]["weight_pct"], 15.0)
        self.assertEqual(payload["inputs"]["fundamental"]["pe"], 18.0)
        self.assertEqual(payload["inputs"]["technical"]["relative_strength"], 0.8)
        self.assertEqual(payload["inputs"]["technical"]["rsi"], 55.0)
        self.assertEqual(payload["inputs"]["capital_flow"]["main_net_inflow"], 1000.0)
        self.assertEqual(payload["inputs"]["sentiment"]["limit_up_streak"], 1)
        self.assertIn("PE is within", payload["components"]["fundamental"]["reasons"][0])


if __name__ == "__main__":
    unittest.main()
