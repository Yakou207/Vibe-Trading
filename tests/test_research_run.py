from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class ResearchRunTest(unittest.TestCase):
    def test_run_research_baseline_outputs_scores_trades_equity_and_summary(self) -> None:
        from fintech_quant.research.run import ResearchRunConfig, run_research_baseline

        with tempfile.TemporaryDirectory() as tmp:
            paths = _write_fixture_inputs(Path(tmp))
            report = run_research_baseline(
                ResearchRunConfig(
                    run_id="fixture-run",
                    features_path=paths["features"],
                    universe_path=paths["universe"],
                    fundamentals_path=paths["fundamentals"],
                    capital_flow_path=paths["capital_flow"],
                    initial_cash=100000.0,
                )
            )

        self.assertEqual(report.run_id, "fixture-run")
        self.assertGreater(len(report.scores), 0)
        self.assertGreater(len(report.trades), 0)
        self.assertGreater(len(report.equity_curve), 0)
        self.assertIn("max_drawdown", report.summary)
        self.assertEqual(report.summary["trade_count"], 1)

    def test_write_run_report_serializes_stable_json(self) -> None:
        from fintech_quant.research.run import ResearchRunConfig, run_research_baseline, write_run_report

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _write_fixture_inputs(root)
            report = run_research_baseline(
                ResearchRunConfig(
                    run_id="fixture-run",
                    features_path=paths["features"],
                    universe_path=paths["universe"],
                    fundamentals_path=paths["fundamentals"],
                    capital_flow_path=paths["capital_flow"],
                    initial_cash=100000.0,
                )
            )

            report_path = write_run_report(report, root / "outputs")
            payload = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["run_id"], "fixture-run")
        self.assertEqual(report_path.name, "run_report.json")
        self.assertIn("scores", payload)
        self.assertIn("risk_warnings", payload)
        self.assertIn("summary", payload)
        self.assertEqual(payload["scores"][0]["symbol"], "000001.SZ")
        self.assertIn("points", payload["drawdown"])
        self.assertEqual(payload["drawdown"]["points"][0]["trade_date"], "2026-01-01")
        self.assertIn("rolling_peak", payload["drawdown"]["points"][0])

    def test_run_research_baseline_passes_price_limit_flags_to_portfolio_runner(self) -> None:
        from fintech_quant.research.run import ResearchRunConfig, run_research_baseline

        with tempfile.TemporaryDirectory() as tmp:
            paths = _write_fixture_inputs(Path(tmp), limit_up=True)
            report = run_research_baseline(
                ResearchRunConfig(
                    run_id="limit-up-run",
                    features_path=paths["features"],
                    universe_path=paths["universe"],
                    fundamentals_path=paths["fundamentals"],
                    capital_flow_path=paths["capital_flow"],
                    initial_cash=100000.0,
                )
            )

        self.assertEqual(report.trades, [])
        self.assertEqual(report.summary["trade_count"], 0)

    def test_run_research_baseline_links_information_capital_market_risk_and_drawdown(self) -> None:
        from fintech_quant.research.run import ResearchRunConfig, run_research_baseline

        with tempfile.TemporaryDirectory() as tmp:
            paths = _write_full_loop_fixture(Path(tmp))
            report = run_research_baseline(
                ResearchRunConfig(
                    run_id="full-loop",
                    features_path=paths["features"],
                    universe_path=paths["universe"],
                    information_path=paths["information"],
                    fundamentals_path=paths["fundamentals"],
                    capital_flow_path=paths["capital_flow"],
                    market_state_path=paths["market_state"],
                    initial_cash=100000.0,
                )
            )

        scores_by_date = {row["trade_date"]: row for row in report.scores}
        second_day_sentiment = scores_by_date["2026-01-02"]["components"]["sentiment"]
        warning_rules = {row["rule"] for row in report.risk_warnings}
        trade_actions = [row["action"] for row in report.trades]

        self.assertLess(second_day_sentiment["score"], scores_by_date["2026-01-01"]["components"]["sentiment"]["score"])
        self.assertIn("main_outflow_days", warning_rules)
        self.assertIn("broad_market_drop_gt_3pct_count", warning_rules)
        self.assertEqual(trade_actions, ["buy", "sell"])
        self.assertGreater(len(report.equity_curve), 0)
        self.assertGreater(report.drawdown["max_drawdown"], 0.0)
        self.assertEqual(report.drawdown["max_drawdown"], report.summary["max_drawdown"])
        self.assertEqual(
            report.drawdown["points"],
            [
                {
                    "trade_date": "2026-01-01",
                    "equity": 99997.6,
                    "rolling_peak": 99997.6,
                    "drawdown": 0.0,
                },
                {
                    "trade_date": "2026-01-02",
                    "equity": 99195.44,
                    "rolling_peak": 99997.6,
                    "drawdown": 0.008022,
                },
            ],
        )


def _write_fixture_inputs(root: Path, *, limit_up: bool = False) -> dict[str, Path]:
    universe = root / "universe.csv"
    features = root / "features.csv"
    fundamentals = root / "fundamentals.csv"
    capital_flow = root / "capital_flow.csv"
    universe.write_text("symbol,name,sector\n000001,Ping An,Bank\n", encoding="utf-8")
    features.write_text(
        "symbol,trade_date,open,high,low,close,volume,amount,source,return_1d,ma20,ma60,ma250,"
        "close_above_ma20,close_above_ma60,close_above_ma250,rsi14,macd_line,macd_signal,macd_hist,"
        "macd_positive,volatility20,limit_up\n"
        f"000001,2026-01-01,10,10,10,10,1000,10000,fixture,0.01,9,8,7,true,true,true,55,0.1,0.05,0.05,true,0.02,{str(limit_up).lower()}\n",
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


def _write_full_loop_fixture(root: Path) -> dict[str, Path]:
    universe = root / "universe.csv"
    features = root / "features.csv"
    fundamentals = root / "fundamentals.csv"
    capital_flow = root / "capital_flow.csv"
    market_state = root / "market_state.csv"
    information = root / "information.jsonl"
    universe.write_text("symbol,name,sector\n000001,Ping An,新能源\n", encoding="utf-8")
    features.write_text(
        "symbol,trade_date,open,high,low,close,volume,amount,source,return_1d,ma20,ma60,ma250,"
        "close_above_ma20,close_above_ma60,close_above_ma250,rsi14,macd_line,macd_signal,macd_hist,"
        "macd_positive,volatility20\n"
        "000001,2026-01-01,10,10,10,10,1000,10000,fixture,0.01,9,8,7,true,true,true,55,0.1,0.05,0.05,true,0.02\n"
        "000001,2026-01-02,10,10,10,9,1000,9000,fixture,-0.10,9,8,7,true,true,true,55,0.1,0.05,0.05,true,0.02\n",
        encoding="utf-8",
    )
    fundamentals.write_text("symbol,pe,pb,roe,growth\n000001,18,1.5,0.16,0.12\n", encoding="utf-8")
    capital_flow.write_text(
        "symbol,trade_date,main_net_inflow,main_outflow_days,margin_financing_positive\n"
        "000001,2026-01-01,1000,0,true\n"
        "000001,2026-01-02,-2000,4,false\n",
        encoding="utf-8",
    )
    market_state.write_text(
        "trade_date,index_below_annual_ma,broad_market_drop_gt_3pct_count\n"
        "2026-01-01,false,0\n"
        "2026-01-02,true,16\n",
        encoding="utf-8",
    )
    information.write_text(
        '{"symbol": null, "sector": "新能源", "published_at": "2026-01-02", '
        '"source": "fixture", "category": "regulatory_policy", "title": "Sector regulatory pressure", '
        '"url": "https://example.test/policy", "summary": "Policy fixture.", '
        '"risk_tags": ["regulatory_risk"]}\n',
        encoding="utf-8",
    )
    return {
        "universe": universe,
        "features": features,
        "fundamentals": fundamentals,
        "capital_flow": capital_flow,
        "market_state": market_state,
        "information": information,
    }


if __name__ == "__main__":
    unittest.main()
