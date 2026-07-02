from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path


class Phase4ResearchDatasetTest(unittest.TestCase):
    def test_load_research_dataset_normalizes_sorts_and_filters_universe(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            features_path = root / "features.csv"
            universe_path.write_text("symbol,name,sector\n000001,Ping An,Bank\n", encoding="utf-8")
            _write_csv(
                features_path,
                [
                    _feature_row("600000.SH", "2026-01-01", 20.0),
                    _feature_row("000001", "2026-01-02", 11.0),
                    _feature_row("000001", "2026-01-01", 10.0),
                ],
            )

            dataset = load_research_dataset(features_path, universe_path)

        self.assertEqual(dataset.universe_symbols, ("000001.SZ",))
        self.assertEqual(
            [(row.trade_date.isoformat(), row.symbol) for row in dataset.features],
            [("2026-01-01", "000001.SZ"), ("2026-01-02", "000001.SZ")],
        )
        self.assertEqual(dataset.features[0].values["close"], 10.0)
        self.assertEqual(dataset.features[0].values["macd_positive"], True)

    def test_load_research_dataset_rejects_duplicate_feature_rows(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            features_path = root / "features.csv"
            universe_path.write_text("symbol\n000001\n", encoding="utf-8")
            _write_csv(
                features_path,
                [
                    _feature_row("000001", "2026-01-01", 10.0),
                    _feature_row("000001.SZ", "2026-01-01", 10.5),
                ],
            )

            with self.assertRaisesRegex(ValueError, "Duplicate feature row"):
                load_research_dataset(features_path, universe_path)

    def test_load_research_dataset_loads_optional_supplemental_files(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            features_path = root / "features.csv"
            fundamentals_path = root / "fundamentals.csv"
            capital_flow_path = root / "capital_flow.csv"
            market_state_path = root / "market_state.csv"
            information_path = root / "information.jsonl"
            universe_path.write_text("symbol,name,sector\n000001,Ping An,Bank\n", encoding="utf-8")
            _write_csv(features_path, [_feature_row("000001", "2026-01-01", 10.0)])
            fundamentals_path.write_text(
                "symbol,pe,pb,roe,growth,goodwill_ratio,pledge_ratio,st_warning\n"
                "000001,18,1.5,0.16,0.12,0.35,0.6,true\n",
                encoding="utf-8",
            )
            capital_flow_path.write_text(
                "symbol,trade_date,main_net_inflow,main_outflow_days,margin_financing_positive\n"
                "000001,2026-01-02,-1000,4,false\n",
                encoding="utf-8",
            )
            market_state_path.write_text(
                "trade_date,index_below_annual_ma,broad_market_drop_gt_3pct_count\n"
                "2026-01-02,true,16\n",
                encoding="utf-8",
            )
            information_path.write_text(
                json.dumps(
                    {
                        "symbol": "000001",
                        "sector": "Bank",
                        "published_at": "2026-01-02",
                        "source": "fixture",
                        "category": "company_announcement",
                        "title": "Risk notice",
                        "url": "https://example.test/risk",
                        "summary": "Risk fixture.",
                        "risk_tags": ["negative_announcement"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            dataset = load_research_dataset(
                features_path,
                universe_path,
                fundamentals_path=fundamentals_path,
                capital_flow_path=capital_flow_path,
                market_state_path=market_state_path,
                information_path=information_path,
            )

        self.assertEqual(dataset.fundamentals[("000001.SZ", None)].values["pe"], 18.0)
        self.assertEqual(dataset.fundamentals[("000001.SZ", None)].values["st_warning"], True)
        self.assertEqual(dataset.capital_flow[("000001.SZ", date(2026, 1, 2))].values["main_outflow_days"], 4)
        self.assertEqual(dataset.market_state[date(2026, 1, 2)].values["index_below_annual_ma"], True)
        self.assertEqual(dataset.information_records[0].title, "Risk notice")
        self.assertEqual(dataset.information_records[0].normalized_symbol, "000001.SZ")

    def test_load_research_dataset_builds_fundamentals_from_information_records(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            features_path = root / "features.csv"
            information_path = root / "information.jsonl"
            universe_path.write_text("symbol,name,sector\n000001,Ping An,Bank\n", encoding="utf-8")
            _write_csv(features_path, [_feature_row("000001", "2026-06-03", 10.0)])
            information_path.write_text(
                json.dumps(
                    {
                        "symbol": "000001",
                        "sector": None,
                        "published_at": "2026-06-03",
                        "source": "akshare_fundamental",
                        "category": "stock_data",
                        "title": "000001.SZ fundamental snapshot",
                        "url": "",
                        "summary": "pe=18.0; pb=1.5; roe=0.16; growth=0.12",
                        "risk_tags": ["selected_universe", "fundamental"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            dataset = load_research_dataset(features_path, universe_path, information_path=information_path)

        row = dataset.fundamentals[("000001.SZ", date(2026, 6, 3))]
        self.assertEqual(row.values["pe"], 18.0)
        self.assertEqual(row.values["pb"], 1.5)
        self.assertEqual(row.values["roe"], 0.16)
        self.assertEqual(row.values["growth"], 0.12)

    def test_explicit_fundamentals_csv_overrides_information_fundamentals(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            features_path = root / "features.csv"
            fundamentals_path = root / "fundamentals.csv"
            information_path = root / "information.jsonl"
            universe_path.write_text("symbol,name,sector\n000001,Ping An,Bank\n", encoding="utf-8")
            _write_csv(features_path, [_feature_row("000001", "2026-06-03", 10.0)])
            fundamentals_path.write_text("symbol,trade_date,pe,pb,roe,growth\n000001,2026-06-03,10,1.0,0.10,0.05\n", encoding="utf-8")
            information_path.write_text(
                json.dumps(
                    {
                        "symbol": "000001",
                        "sector": None,
                        "published_at": "2026-06-03",
                        "source": "akshare_fundamental",
                        "category": "stock_data",
                        "title": "000001.SZ fundamental snapshot",
                        "url": "",
                        "summary": "pe=18.0; pb=1.5; roe=0.16; growth=0.12",
                        "risk_tags": ["selected_universe", "fundamental"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            dataset = load_research_dataset(
                features_path,
                universe_path,
                fundamentals_path=fundamentals_path,
                information_path=information_path,
            )

        self.assertEqual(dataset.fundamentals[("000001.SZ", date(2026, 6, 3))].values["pe"], 10.0)

    def test_static_fundamentals_csv_overrides_dated_information_fundamentals(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            features_path = root / "features.csv"
            fundamentals_path = root / "fundamentals.csv"
            information_path = root / "information.jsonl"
            universe_path.write_text("symbol,name,sector\n000001,Ping An,Bank\n", encoding="utf-8")
            _write_csv(features_path, [_feature_row("000001", "2026-06-03", 10.0)])
            fundamentals_path.write_text("symbol,pe,pb,roe,growth\n000001,10,1.0,0.10,0.05\n", encoding="utf-8")
            information_path.write_text(
                json.dumps(
                    {
                        "symbol": "000001",
                        "sector": None,
                        "published_at": "2026-06-03",
                        "source": "akshare_fundamental",
                        "category": "stock_data",
                        "title": "000001.SZ fundamental snapshot",
                        "url": "",
                        "summary": "pe=18.0; pb=1.5; roe=0.16; growth=0.12",
                        "risk_tags": ["selected_universe", "fundamental"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            dataset = load_research_dataset(
                features_path,
                universe_path,
                fundamentals_path=fundamentals_path,
                information_path=information_path,
            )

        self.assertNotIn(("000001.SZ", date(2026, 6, 3)), dataset.fundamentals)
        self.assertEqual(dataset.fundamentals[("000001.SZ", None)].values["pe"], 10.0)

    def test_information_fundamentals_require_stock_data_category(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            features_path = root / "features.csv"
            information_path = root / "information.jsonl"
            universe_path.write_text("symbol,name,sector\n000001,Ping An,Bank\n", encoding="utf-8")
            _write_csv(features_path, [_feature_row("000001", "2026-06-03", 10.0)])
            information_path.write_text(
                json.dumps(
                    {
                        "symbol": "000001",
                        "sector": None,
                        "published_at": "2026-06-03",
                        "source": "akshare_fundamental",
                        "category": "company_announcement",
                        "title": "Malformed fundamental-like announcement",
                        "url": "",
                        "summary": "pe=18.0; pb=1.5; roe=0.16; growth=0.12",
                        "risk_tags": ["fundamental"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            dataset = load_research_dataset(features_path, universe_path, information_path=information_path)

        self.assertEqual(dataset.fundamentals, {})

    def test_load_research_dataset_builds_capital_flow_from_information_records(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            features_path = root / "features.csv"
            information_path = root / "information.jsonl"
            universe_path.write_text("symbol,name,sector\n000001,Ping An,Bank\n", encoding="utf-8")
            _write_csv(features_path, [_feature_row("000001", "2026-06-03", 10.0)])
            information_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "symbol": "000001",
                                "sector": None,
                                "published_at": "2026-06-01",
                                "source": "akshare_fund_flow",
                                "category": "stock_data",
                                "title": "fund flow",
                                "url": "",
                                "summary": "main_net_inflow=100.0",
                                "risk_tags": ["selected_universe", "capital_flow", "main_inflow"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        json.dumps(
                            {
                                "symbol": "000001",
                                "sector": None,
                                "published_at": "2026-06-02",
                                "source": "akshare_fund_flow",
                                "category": "stock_data",
                                "title": "fund flow",
                                "url": "",
                                "summary": "main_net_inflow=-50.0",
                                "risk_tags": ["selected_universe", "capital_flow", "main_outflow"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        json.dumps(
                            {
                                "symbol": "000001",
                                "sector": None,
                                "published_at": "2026-06-03",
                                "source": "akshare_fund_flow",
                                "category": "stock_data",
                                "title": "fund flow",
                                "url": "",
                                "summary": "main_net_inflow=-60.0",
                                "risk_tags": ["selected_universe", "capital_flow", "main_outflow"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        json.dumps(
                            {
                                "symbol": "000001",
                                "sector": None,
                                "published_at": "2026-06-03",
                                "source": "akshare_margin",
                                "category": "stock_data",
                                "title": "margin financing",
                                "url": "",
                                "summary": "financing_balance=1000.0; short_balance=20.0",
                                "risk_tags": ["selected_universe", "margin_financing"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            dataset = load_research_dataset(features_path, universe_path, information_path=information_path)

        row = dataset.capital_flow[("000001.SZ", date(2026, 6, 3))]
        self.assertEqual(row.values["main_net_inflow"], -60.0)
        self.assertEqual(row.values["main_outflow_days"], 2)
        self.assertNotIn("margin_financing_positive", row.values)

    def test_information_fund_flow_resets_outflow_streak_after_missing_dates(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            features_path = root / "features.csv"
            information_path = root / "information.jsonl"
            universe_path.write_text("symbol,name,sector\n000001,Ping An,Bank\n", encoding="utf-8")
            _write_csv(features_path, [_feature_row("000001", "2026-06-05", 10.0)])
            information_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "symbol": "000001",
                                "sector": None,
                                "published_at": "2026-06-01",
                                "source": "akshare_fund_flow",
                                "category": "stock_data",
                                "title": "fund flow",
                                "url": "",
                                "summary": "main_net_inflow=-50.0",
                                "risk_tags": ["selected_universe", "capital_flow", "main_outflow"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        json.dumps(
                            {
                                "symbol": "000001",
                                "sector": None,
                                "published_at": "2026-06-05",
                                "source": "akshare_fund_flow",
                                "category": "stock_data",
                                "title": "fund flow",
                                "url": "",
                                "summary": "main_net_inflow=-60.0",
                                "risk_tags": ["selected_universe", "capital_flow", "main_outflow"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            dataset = load_research_dataset(features_path, universe_path, information_path=information_path)

        row = dataset.capital_flow[("000001.SZ", date(2026, 6, 5))]
        self.assertEqual(row.values["main_outflow_days"], 1)

    def test_information_fund_flow_skips_malformed_summary(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            features_path = root / "features.csv"
            information_path = root / "information.jsonl"
            universe_path.write_text("symbol,name,sector\n000001,Ping An,Bank\n", encoding="utf-8")
            _write_csv(features_path, [_feature_row("000001", "2026-06-03", 10.0)])
            information_path.write_text(
                json.dumps(
                    {
                        "symbol": "000001",
                        "sector": None,
                        "published_at": "2026-06-03",
                        "source": "akshare_fund_flow",
                        "category": "stock_data",
                        "title": "fund flow",
                        "url": "",
                        "summary": "main_net_amount=100.0",
                        "risk_tags": ["selected_universe", "capital_flow"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            dataset = load_research_dataset(features_path, universe_path, information_path=information_path)

        self.assertEqual(dataset.capital_flow, {})

    def test_information_margin_records_build_financing_direction_from_balance_delta(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            features_path = root / "features.csv"
            information_path = root / "information.jsonl"
            universe_path.write_text("symbol,name,sector\n000001,Ping An,Bank\n", encoding="utf-8")
            _write_csv(
                features_path,
                [
                    _feature_row("000001", "2026-06-01", 10.0),
                    _feature_row("000001", "2026-06-02", 10.5),
                    _feature_row("000001", "2026-06-03", 10.2),
                ],
            )
            information_path.write_text(
                "\n".join(
                    [
                        _information_json(
                            "000001",
                            "2026-06-01",
                            "akshare_margin",
                            "stock_data",
                            "margin financing",
                            "financing_balance=900.0; short_balance=20.0",
                            ["selected_universe", "margin_financing"],
                        ),
                        _information_json(
                            "000001",
                            "2026-06-02",
                            "akshare_margin",
                            "stock_data",
                            "margin financing",
                            "financing_balance=1000.0; short_balance=20.0",
                            ["selected_universe", "margin_financing"],
                        ),
                        _information_json(
                            "000001",
                            "2026-06-03",
                            "akshare_margin",
                            "stock_data",
                            "margin financing",
                            "financing_balance=950.0; short_balance=20.0",
                            ["selected_universe", "margin_financing"],
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            dataset = load_research_dataset(features_path, universe_path, information_path=information_path)

        self.assertNotIn(("000001.SZ", date(2026, 6, 1)), dataset.capital_flow)
        self.assertEqual(dataset.capital_flow[("000001.SZ", date(2026, 6, 2))].values["margin_financing_positive"], True)
        self.assertEqual(dataset.capital_flow[("000001.SZ", date(2026, 6, 3))].values["margin_financing_positive"], False)

    def test_information_margin_records_skip_financing_direction_after_missing_dates(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            features_path = root / "features.csv"
            information_path = root / "information.jsonl"
            universe_path.write_text("symbol,name,sector\n000001,Ping An,Bank\n", encoding="utf-8")
            _write_csv(features_path, [_feature_row("000001", "2026-06-05", 10.0)])
            information_path.write_text(
                "\n".join(
                    [
                        _information_json(
                            "000001",
                            "2026-06-01",
                            "akshare_margin",
                            "stock_data",
                            "margin financing",
                            "financing_balance=900.0",
                            ["selected_universe", "margin_financing"],
                        ),
                        _information_json(
                            "000001",
                            "2026-06-05",
                            "akshare_margin",
                            "stock_data",
                            "margin financing",
                            "financing_balance=1000.0",
                            ["selected_universe", "margin_financing"],
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            dataset = load_research_dataset(features_path, universe_path, information_path=information_path)

        self.assertEqual(dataset.capital_flow, {})

    def test_explicit_capital_flow_csv_overrides_information_capital_flow(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            features_path = root / "features.csv"
            capital_flow_path = root / "capital_flow.csv"
            information_path = root / "information.jsonl"
            universe_path.write_text("symbol,name,sector\n000001,Ping An,Bank\n", encoding="utf-8")
            _write_csv(features_path, [_feature_row("000001", "2026-06-03", 10.0)])
            capital_flow_path.write_text(
                "symbol,trade_date,main_net_inflow,main_outflow_days,margin_financing_positive\n"
                "000001,2026-06-03,999,0,true\n",
                encoding="utf-8",
            )
            information_path.write_text(
                json.dumps(
                    {
                        "symbol": "000001",
                        "sector": None,
                        "published_at": "2026-06-03",
                        "source": "akshare_fund_flow",
                        "category": "stock_data",
                        "title": "fund flow",
                        "url": "",
                        "summary": "main_net_inflow=-60.0",
                        "risk_tags": ["selected_universe", "capital_flow", "main_outflow"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            dataset = load_research_dataset(
                features_path,
                universe_path,
                capital_flow_path=capital_flow_path,
                information_path=information_path,
            )

        row = dataset.capital_flow[("000001.SZ", date(2026, 6, 3))]
        self.assertEqual(row.values["main_net_inflow"], 999.0)
        self.assertEqual(row.values["main_outflow_days"], 0)

    def test_explicit_capital_flow_csv_excludes_information_record_from_next_outflow_streak(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            features_path = root / "features.csv"
            capital_flow_path = root / "capital_flow.csv"
            information_path = root / "information.jsonl"
            universe_path.write_text("symbol,name,sector\n000001,Ping An,Bank\n", encoding="utf-8")
            _write_csv(features_path, [_feature_row("000001", "2026-06-02", 10.0)])
            capital_flow_path.write_text(
                "symbol,trade_date,main_net_inflow,main_outflow_days\n"
                "000001,2026-06-01,999,0\n",
                encoding="utf-8",
            )
            information_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "symbol": "000001",
                                "sector": None,
                                "published_at": "2026-06-01",
                                "source": "akshare_fund_flow",
                                "category": "stock_data",
                                "title": "fund flow",
                                "url": "",
                                "summary": "main_net_inflow=-50.0",
                                "risk_tags": ["selected_universe", "capital_flow", "main_outflow"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        json.dumps(
                            {
                                "symbol": "000001",
                                "sector": None,
                                "published_at": "2026-06-02",
                                "source": "akshare_fund_flow",
                                "category": "stock_data",
                                "title": "fund flow",
                                "url": "",
                                "summary": "main_net_inflow=-60.0",
                                "risk_tags": ["selected_universe", "capital_flow", "main_outflow"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            dataset = load_research_dataset(
                features_path,
                universe_path,
                capital_flow_path=capital_flow_path,
                information_path=information_path,
            )

        row = dataset.capital_flow[("000001.SZ", date(2026, 6, 2))]
        self.assertEqual(row.values["main_net_inflow"], -60.0)
        self.assertEqual(row.values["main_outflow_days"], 1)

    def test_explicit_capital_flow_csv_resets_outflow_streak_between_information_records(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            features_path = root / "features.csv"
            capital_flow_path = root / "capital_flow.csv"
            information_path = root / "information.jsonl"
            universe_path.write_text("symbol,name,sector\n000001,Ping An,Bank\n", encoding="utf-8")
            _write_csv(features_path, [_feature_row("000001", "2026-06-02", 10.0)])
            capital_flow_path.write_text(
                "symbol,trade_date,main_net_inflow,main_outflow_days\n"
                "000001,2026-06-01,999,0\n",
                encoding="utf-8",
            )
            information_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "symbol": "000001",
                                "sector": None,
                                "published_at": "2026-05-31",
                                "source": "akshare_fund_flow",
                                "category": "stock_data",
                                "title": "fund flow",
                                "url": "",
                                "summary": "main_net_inflow=-50.0",
                                "risk_tags": ["selected_universe", "capital_flow", "main_outflow"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        json.dumps(
                            {
                                "symbol": "000001",
                                "sector": None,
                                "published_at": "2026-06-02",
                                "source": "akshare_fund_flow",
                                "category": "stock_data",
                                "title": "fund flow",
                                "url": "",
                                "summary": "main_net_inflow=-60.0",
                                "risk_tags": ["selected_universe", "capital_flow", "main_outflow"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            dataset = load_research_dataset(
                features_path,
                universe_path,
                capital_flow_path=capital_flow_path,
                information_path=information_path,
            )

        row = dataset.capital_flow[("000001.SZ", date(2026, 6, 2))]
        self.assertEqual(row.values["main_net_inflow"], -60.0)
        self.assertEqual(row.values["main_outflow_days"], 1)

    def test_load_research_dataset_rejects_missing_explicit_information_path(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            features_path = root / "features.csv"
            universe_path.write_text("symbol\n000001\n", encoding="utf-8")
            _write_csv(features_path, [_feature_row("000001", "2026-01-01", 10.0)])

            with self.assertRaises(FileNotFoundError):
                load_research_dataset(features_path, universe_path, information_path=root / "missing.jsonl")


def _information_json(
    symbol: str | None,
    published_at: str,
    source: str,
    category: str,
    title: str,
    summary: str,
    risk_tags: list[str],
) -> str:
    return json.dumps(
        {
            "symbol": symbol,
            "sector": None,
            "published_at": published_at,
            "source": source,
            "category": category,
            "title": title,
            "url": "",
            "summary": summary,
            "risk_tags": risk_tags,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = list(rows[0])
    lines = [",".join(fieldnames)]
    for row in rows:
        lines.append(",".join(str(row[field]) for field in fieldnames))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _feature_row(symbol: str, trade_date: str, close: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1000,
        "amount": close * 1000,
        "source": "fixture",
        "return_1d": 0.01,
        "ma20": close - 1,
        "ma60": close - 2,
        "ma250": close - 3,
        "close_above_ma20": "true",
        "close_above_ma60": "true",
        "close_above_ma250": "true",
        "rsi14": 55,
        "macd_line": 0.1,
        "macd_signal": 0.05,
        "macd_hist": 0.05,
        "macd_positive": "true",
        "volatility20": 0.02,
    }


if __name__ == "__main__":
    unittest.main()
