from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class ResearchRunTest(unittest.TestCase):
    def test_research_run_defaults_to_next_session_execution(self) -> None:
        from fintech_quant.research.run import ResearchRunConfig

        config = ResearchRunConfig(
            run_id="timing",
            features_path=Path("features.csv"),
            universe_path=Path("universe.csv"),
        )

        self.assertEqual(config.execution_delay_sessions, 1)
        self.assertEqual(config.minimum_commission, 5.0)

    def test_research_run_config_rejects_invalid_ratios_and_thresholds(self) -> None:
        from fintech_quant.research.run import ResearchRunConfig

        base_config = {
            "run_id": "invalid-config",
            "features_path": Path("features.csv"),
            "universe_path": Path("universe.csv"),
        }

        invalid_cases = [
            ("initial_cash", 0),
            ("max_position_weight", 0),
            ("commission_rate", -0.001),
            ("slippage_rate", -0.001),
            ("buy_threshold", -1),
            ("min_score_confidence", 1.2),
            ("max_portfolio_drawdown", -0.1),
            ("max_single_position_drawdown", 1.5),
            ("max_goodwill_ratio", -0.1),
            ("max_pledge_ratio", 1.1),
            ("max_main_outflow_days", -1),
            ("broad_market_drop_threshold", -1),
        ]

        for field, value in invalid_cases:
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, field):
                    ResearchRunConfig(**base_config, **{field: value})

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
                    buy_threshold=65.0,
                    min_score_confidence=0.75,
                    max_portfolio_drawdown=0.12,
                    max_single_position_drawdown=0.06,
                    max_goodwill_ratio=0.25,
                    max_pledge_ratio=0.45,
                    max_main_outflow_days=2,
                    broad_market_drop_threshold=10,
                    execution_delay_sessions=0,
                )
            )

        self.assertEqual(report.run_id, "fixture-run")
        self.assertEqual(report.strategy_config["buy_threshold"], 65.0)
        self.assertEqual(report.strategy_config["min_confidence"], 0.75)
        self.assertEqual(report.strategy_config["commission_rate"], 0.0003)
        self.assertEqual(report.strategy_config["minimum_commission"], 5.0)
        self.assertEqual(report.strategy_config["slippage_rate"], 0.0)
        self.assertEqual(report.strategy_config["include_stamp_duty"], True)
        self.assertEqual(report.risk_limits["max_portfolio_drawdown"], 0.12)
        self.assertEqual(report.risk_limits["max_single_position_drawdown"], 0.06)
        self.assertEqual(report.risk_limits["max_goodwill_ratio"], 0.25)
        self.assertEqual(report.risk_limits["max_pledge_ratio"], 0.45)
        self.assertEqual(report.risk_limits["max_main_outflow_days"], 2)
        self.assertEqual(report.risk_limits["broad_market_drop_threshold"], 10)
        self.assertGreater(len(report.scores), 0)
        self.assertGreater(len(report.trades), 0)
        self.assertGreater(len(report.equity_curve), 0)
        self.assertIn("max_drawdown", report.summary)
        self.assertEqual(report.summary["trade_count"], 1)

    def test_research_run_loads_external_unadjusted_execution_prices(self) -> None:
        from fintech_quant.research.run import ResearchRunConfig, run_research_baseline

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _write_fixture_inputs(root)
            execution_prices = root / "execution_prices.csv"
            execution_prices.write_text(
                "symbol,trade_date,open,high,low,close,volume,amount,source\n"
                "000001.SZ,2026-01-01,20,20,20,20,1000,20000,unadjusted\n",
                encoding="utf-8",
            )
            report = run_research_baseline(
                ResearchRunConfig(
                    run_id="dual-price",
                    features_path=paths["features"],
                    execution_prices_path=execution_prices,
                    universe_path=paths["universe"],
                    fundamentals_path=paths["fundamentals"],
                    capital_flow_path=paths["capital_flow"],
                    initial_cash=100000.0,
                    execution_delay_sessions=0,
                    minimum_commission=0.0,
                    include_stamp_duty=False,
                )
            )

        self.assertEqual(report.trades[0]["price"], 20.0)
        self.assertEqual(report.trades[0]["shares"], 400)
        self.assertEqual(report.inputs["execution_prices"], str(execution_prices))
        self.assertEqual(report.summary["execution_price_mode"], "unadjusted_external")

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
                    execution_delay_sessions=0,
                    minimum_commission=0.0,
                    include_stamp_duty=False,
                )
            )

            report_path = write_run_report(report, root / "outputs")
            payload = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["run_id"], "fixture-run")
        self.assertEqual(report_path.name, "run_report.json")
        self.assertIn("scores", payload)
        self.assertIn("risk_warnings", payload)
        self.assertIn("risk_summary", payload)
        self.assertIn("summary", payload)
        self.assertEqual(payload["risk_summary"]["total_warnings"], 0)
        self.assertEqual(payload["strategy_config"]["min_confidence"], 0.8)
        self.assertEqual(payload["risk_limits"]["max_portfolio_drawdown"], 0.15)
        self.assertEqual(payload["scores"][0]["symbol"], "000001.SZ")
        self.assertIn("points", payload["drawdown"])
        self.assertIn("episodes", payload["drawdown"])
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
        from fintech_quant.research.run import ResearchRunConfig, run_research_baseline, write_run_report

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
                    execution_delay_sessions=0,
                    minimum_commission=0.0,
                    include_stamp_duty=False,
                )
            )
            report_path = write_run_report(report, paths["features"].parent / "outputs")
            written_risk_summary = json.loads(report_path.read_text(encoding="utf-8"))["risk_summary"]

        scores_by_date = {row["trade_date"]: row for row in report.scores}
        second_day_sentiment = scores_by_date["2026-01-02"]["components"]["sentiment"]
        warning_rules = {row["rule"] for row in report.risk_warnings}
        warnings_by_rule = {row["rule"]: row for row in report.risk_warnings}
        trade_actions = [row["action"] for row in report.trades]

        self.assertLess(second_day_sentiment["score"], scores_by_date["2026-01-01"]["components"]["sentiment"]["score"])
        self.assertIn("negative_event_count", warning_rules)
        self.assertIn("main_outflow_days", warning_rules)
        self.assertIn("broad_market_drop_gt_3pct_count", warning_rules)
        self.assertEqual(report.risk_summary["total_warnings"], len(report.risk_warnings))
        self.assertEqual(report.risk_summary["by_layer"]["broad_market_abnormal"], 1)
        self.assertEqual(report.risk_summary["by_layer"]["systemic_risk"], 1)
        self.assertEqual(report.risk_summary["by_rule"]["main_outflow_days"], 1)
        self.assertGreaterEqual(report.risk_summary["by_action"]["reduce"], 1)
        self.assertEqual(written_risk_summary, report.risk_summary)
        self.assertEqual(warnings_by_rule["main_outflow_days"]["observed_value"], 4)
        self.assertEqual(warnings_by_rule["main_outflow_days"]["threshold_value"], 3)
        self.assertEqual(warnings_by_rule["broad_market_drop_gt_3pct_count"]["observed_value"], 16)
        self.assertEqual(warnings_by_rule["broad_market_drop_gt_3pct_count"]["threshold_value"], 15)
        self.assertEqual(trade_actions, ["buy", "sell"])
        self.assertIn("realized_pnl", report.trades[1])
        self.assertLess(report.trades[1]["realized_pnl"], 0.0)
        self.assertGreater(len(report.equity_curve), 0)
        self.assertGreater(report.drawdown["max_drawdown"], 0.0)
        self.assertEqual(report.drawdown["max_drawdown"], report.summary["max_drawdown"])
        self.assertEqual(report.drawdown["max_drawdown_start"], "2026-01-01")
        self.assertEqual(report.drawdown["max_drawdown_end"], "2026-01-02")
        self.assertIsNone(report.drawdown["recovery_date"])
        self.assertEqual(report.drawdown["current_drawdown_start"], "2026-01-01")
        self.assertEqual(report.drawdown["current_underwater_days"], 2)
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
        self.assertEqual(report.drawdown["episodes"][0]["start_date"], "2026-01-01")
        self.assertEqual(report.drawdown["episodes"][0]["trough_date"], "2026-01-02")
        self.assertIsNone(report.drawdown["episodes"][0]["recovery_date"])
        self.assertEqual(report.drawdown["episodes"][0]["duration_days"], 2)

    def test_run_research_baseline_warns_on_financial_statement_goodwill_ratio(self) -> None:
        from fintech_quant.research.run import ResearchRunConfig, run_research_baseline

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _write_fixture_inputs(root)
            information_path = root / "information.jsonl"
            information_path.write_text(
                json.dumps(
                    {
                        "symbol": "000001",
                        "sector": None,
                        "published_at": "2026-01-01",
                        "source": "akshare_financial_statement",
                        "category": "stock_data",
                        "title": "000001.SZ 资产负债表 2026-01-01",
                        "url": "",
                        "summary": "goodwill=4000; total_assets=10000",
                        "risk_tags": ["selected_universe", "financial_statement", "balance_sheet"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            report = run_research_baseline(
                ResearchRunConfig(
                    run_id="goodwill-risk",
                    features_path=paths["features"],
                    universe_path=paths["universe"],
                    information_path=information_path,
                    capital_flow_path=paths["capital_flow"],
                    initial_cash=100000.0,
                    execution_delay_sessions=0,
                )
            )

        self.assertIn("goodwill_ratio", {warning["rule"] for warning in report.risk_warnings})

    def test_run_research_baseline_warns_on_information_pledge_ratio(self) -> None:
        from fintech_quant.research.run import ResearchRunConfig, run_research_baseline

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _write_fixture_inputs(root)
            information_path = root / "information.jsonl"
            information_path.write_text(
                json.dumps(
                    {
                        "symbol": "000001",
                        "sector": None,
                        "published_at": "2026-01-01",
                        "source": "akshare_pledge_ratio",
                        "category": "stock_data",
                        "title": "000001.SZ pledge ratio",
                        "url": "",
                        "summary": "pledge_ratio=0.51",
                        "risk_tags": ["selected_universe", "pledge_ratio"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            report = run_research_baseline(
                ResearchRunConfig(
                    run_id="pledge-risk",
                    features_path=paths["features"],
                    universe_path=paths["universe"],
                    information_path=information_path,
                    capital_flow_path=paths["capital_flow"],
                    initial_cash=100000.0,
                    execution_delay_sessions=0,
                )
            )

        self.assertIn("pledge_ratio", {warning["rule"] for warning in report.risk_warnings})

    def test_run_research_baseline_warns_on_information_st_status(self) -> None:
        from fintech_quant.research.run import ResearchRunConfig, run_research_baseline

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _write_fixture_inputs(root)
            information_path = root / "information.jsonl"
            information_path.write_text(
                json.dumps(
                    {
                        "symbol": "000001",
                        "sector": None,
                        "published_at": "2026-01-01",
                        "source": "akshare_st_status",
                        "category": "stock_data",
                        "title": "000001.SZ ST status",
                        "url": "",
                        "summary": "st_warning=true; stock_name=*ST平安",
                        "risk_tags": ["selected_universe", "st_warning"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            report = run_research_baseline(
                ResearchRunConfig(
                    run_id="st-risk",
                    features_path=paths["features"],
                    universe_path=paths["universe"],
                    information_path=information_path,
                    capital_flow_path=paths["capital_flow"],
                    initial_cash=100000.0,
                    execution_delay_sessions=0,
                )
            )

        self.assertIn("st_warning", {warning["rule"] for warning in report.risk_warnings})


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
