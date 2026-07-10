from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
import json
from pathlib import Path


class InformationRepositoryTest(unittest.TestCase):
    def test_append_deduplicates_by_stable_key(self) -> None:
        from fintech_quant.information import InformationCategory, InformationRecord, InformationRepository

        with tempfile.TemporaryDirectory() as tmp:
            repo = InformationRepository(Path(tmp) / "info.jsonl")
            record = InformationRecord(
                symbol="000001",
                sector=None,
                published_at=date(2026, 1, 2),
                source="exchange",
                category=InformationCategory.FINANCIAL_REPORT,
                title="Annual report",
                url="https://example.test/report",
                summary="Revenue grew.",
                risk_tags=("financial_report",),
            )

            self.assertTrue(repo.append(record))
            self.assertFalse(repo.append(record))
            self.assertEqual(len(repo.query(symbol="000001")), 1)

    def test_prune_text_records_keeps_recent_three_years_only(self) -> None:
        from fintech_quant.information import InformationCategory, InformationRecord, InformationRepository

        with tempfile.TemporaryDirectory() as tmp:
            repo = InformationRepository(Path(tmp) / "info.jsonl")
            old_text = InformationRecord(
                symbol="000001",
                sector=None,
                published_at=date(2022, 1, 1),
                source="exchange",
                category=InformationCategory.COMPANY_ANNOUNCEMENT,
                title="Old announcement",
                url="https://example.test/old",
                summary="Old text.",
                risk_tags=(),
            )
            recent_text = InformationRecord(
                symbol="000001",
                sector=None,
                published_at=date(2025, 6, 18),
                source="exchange",
                category=InformationCategory.COMPANY_ANNOUNCEMENT,
                title="Recent announcement",
                url="https://example.test/recent",
                summary="Recent text.",
                risk_tags=(),
            )

            repo.append(old_text)
            repo.append(recent_text)

            removed = repo.prune_text_records(today=date(2026, 6, 18))

            self.assertEqual(removed, 1)
            self.assertEqual([record.title for record in repo.query(symbol="000001")], ["Recent announcement"])

    def test_selected_universe_stock_data_is_not_pruned_by_text_policy(self) -> None:
        from fintech_quant.information import InformationCategory, InformationRecord, InformationRepository

        with tempfile.TemporaryDirectory() as tmp:
            repo = InformationRepository(Path(tmp) / "info.jsonl")
            old_stock_data = InformationRecord(
                symbol="000001",
                sector=None,
                published_at=date(2019, 1, 1),
                source="local",
                category=InformationCategory.STOCK_DATA,
                title="Selected universe training row",
                url="",
                summary="Retained for RL.",
                risk_tags=("selected_universe",),
            )

            repo.append(old_stock_data)
            removed = repo.prune_text_records(today=date(2026, 6, 18))

            self.assertEqual(removed, 0)
            self.assertEqual(len(repo.query(symbol="000001")), 1)

    def test_export_by_retention_class_writes_split_jsonl_files_and_manifest(self) -> None:
        from fintech_quant.information import InformationCategory, InformationRecord, InformationRepository

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = InformationRepository(root / "info.jsonl")
            repo.append(
                InformationRecord(
                    symbol="000001",
                    sector=None,
                    published_at=date(2026, 1, 2),
                    source="exchange",
                    category=InformationCategory.FINANCIAL_REPORT,
                    title="Annual report",
                    url="https://example.test/report",
                    summary="Revenue grew.",
                    risk_tags=("financial_report",),
                )
            )
            repo.append(
                InformationRecord(
                    symbol="000001",
                    sector=None,
                    published_at=date(2021, 1, 2),
                    source="akshare",
                    category=InformationCategory.STOCK_DATA,
                    title="Training data",
                    url="",
                    summary="pe=12.0",
                    risk_tags=("selected_universe", "fundamental"),
                )
            )

            manifest = repo.export_by_retention_class(root / "classified")

            text_path = root / "classified" / "text_financial_report.jsonl"
            stock_data_path = root / "classified" / "selected_universe_stock_data.jsonl"
            manifest_path = root / "classified" / "manifest.json"
            self.assertTrue(text_path.exists())
            self.assertTrue(stock_data_path.exists())
            self.assertTrue(manifest_path.exists())
            self.assertIn("Annual report", text_path.read_text(encoding="utf-8"))
            self.assertNotIn("Training data", text_path.read_text(encoding="utf-8"))
            self.assertIn("Training data", stock_data_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["classes"]["text_financial_report"]["record_count"], 1)
            self.assertEqual(manifest["classes"]["selected_universe_stock_data"]["record_count"], 1)
            self.assertEqual(manifest["classes"]["selected_universe_stock_data"]["symbols"], ["000001.SZ"])

    def test_stock_data_requires_selected_universe_tag(self) -> None:
        from fintech_quant.information import InformationCategory, InformationRecord

        with self.assertRaisesRegex(ValueError, "selected_universe"):
            InformationRecord(
                symbol="000001",
                sector=None,
                published_at=date(2019, 1, 1),
                source="local",
                category=InformationCategory.STOCK_DATA,
                title="Non-selected training row",
                url="",
                summary="Should be rejected.",
                risk_tags=(),
            )

    def test_prune_text_records_handles_leap_day_cutoff(self) -> None:
        from fintech_quant.information import InformationCategory, InformationRecord, InformationRepository

        with tempfile.TemporaryDirectory() as tmp:
            repo = InformationRepository(Path(tmp) / "info.jsonl")
            old_text = InformationRecord(
                symbol="000001",
                sector=None,
                published_at=date(2025, 2, 27),
                source="exchange",
                category=InformationCategory.COMPANY_ANNOUNCEMENT,
                title="Before leap cutoff",
                url="https://example.test/before-leap",
                summary="Old text.",
                risk_tags=(),
            )
            boundary_text = InformationRecord(
                symbol="000001",
                sector=None,
                published_at=date(2025, 2, 28),
                source="exchange",
                category=InformationCategory.COMPANY_ANNOUNCEMENT,
                title="Leap cutoff boundary",
                url="https://example.test/leap-boundary",
                summary="Boundary text.",
                risk_tags=(),
            )

            repo.append(old_text)
            repo.append(boundary_text)

            removed = repo.prune_text_records(today=date(2028, 2, 29))

            self.assertEqual(removed, 1)
            self.assertEqual([record.title for record in repo.query(symbol="000001")], ["Leap cutoff boundary"])

    def test_fetch_information_script_populates_repository_from_jsonl_fixture(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as tmp:
            fixture_path = Path(tmp) / "fixture.jsonl"
            output_path = Path(tmp) / "output.jsonl"
            fixture_path.write_text(
                json.dumps(
                    {
                        "symbol": "000001.SZ",
                        "sector": "banking",
                        "published_at": "2026-01-15",
                        "source": "fixture",
                        "category": "company_announcement",
                        "title": "Fixture announcement",
                        "url": "https://example.test/fixture-announcement",
                        "summary": "Fixture-backed announcement.",
                        "risk_tags": [],
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
                    "scripts/fetch_information.py",
                    "--source",
                    "jsonl",
                    "--input",
                    str(fixture_path),
                    "--symbol",
                    "000001",
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-01-31",
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
            self.assertEqual(result.stdout.strip(), "stored_records=1\npruned_text_records=0")
            self.assertEqual(result.stderr, "")
            self.assertIn("Fixture announcement", output_path.read_text(encoding="utf-8"))

    def test_export_information_repository_script_writes_classified_outputs(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "information.jsonl"
            output_dir = root / "classified"
            input_path.write_text(
                json.dumps(
                    {
                        "symbol": "000001.SZ",
                        "sector": None,
                        "published_at": "2026-01-15",
                        "source": "fixture",
                        "category": "stock_data",
                        "title": "Training row",
                        "url": "",
                        "summary": "pe=12.0",
                        "risk_tags": ["selected_universe", "fundamental"],
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
                    "scripts/export_information_repository.py",
                    "--input",
                    str(input_path),
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(f"manifest_path={output_dir / 'manifest.json'}", result.stdout)
        self.assertEqual(manifest["classes"]["selected_universe_stock_data"]["record_count"], 1)

    def test_fetch_information_script_prunes_old_text_records_after_append(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as tmp:
            fixture_path = Path(tmp) / "fixture.jsonl"
            output_path = Path(tmp) / "output.jsonl"
            fixture_path.write_text(
                json.dumps(
                    {
                        "symbol": "000001.SZ",
                        "sector": "banking",
                        "published_at": "2026-01-15",
                        "source": "fixture",
                        "category": "company_announcement",
                        "title": "Fixture announcement",
                        "url": "https://example.test/fixture-announcement",
                        "summary": "Fixture-backed announcement.",
                        "risk_tags": [],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            output_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "symbol": "000001.SZ",
                                "sector": "banking",
                                "published_at": "2022-01-15",
                                "source": "fixture",
                                "category": "company_announcement",
                                "title": "Old announcement",
                                "url": "https://example.test/old-announcement",
                                "summary": "Should be pruned.",
                                "risk_tags": [],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        json.dumps(
                            {
                                "symbol": "000001.SZ",
                                "sector": "banking",
                                "published_at": "2019-01-01",
                                "source": "local",
                                "category": "stock_data",
                                "title": "Selected universe training row",
                                "url": "",
                                "summary": "Retained for RL.",
                                "risk_tags": ["selected_universe"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/fetch_information.py",
                    "--source",
                    "jsonl",
                    "--input",
                    str(fixture_path),
                    "--symbol",
                    "000001",
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-01-31",
                    "--output",
                    str(output_path),
                    "--retention-as-of",
                    "2026-06-18",
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertEqual(result.stdout.strip(), "stored_records=1\npruned_text_records=1")
            self.assertEqual(result.stderr, "")
            stored_text = output_path.read_text(encoding="utf-8")
            self.assertIn("Fixture announcement", stored_text)
            self.assertIn("Selected universe training row", stored_text)
            self.assertNotIn("Old announcement", stored_text)

    def test_jsonl_fetcher_reads_source_backed_records(self) -> None:
        from fintech_quant.information import JsonlInformationFetcher

        with tempfile.TemporaryDirectory() as tmp:
            fixture_path = Path(tmp) / "fixture.jsonl"
            fixture_path.write_text(
                json.dumps(
                    {
                        "symbol": "000001.SZ",
                        "sector": "banking",
                        "published_at": "2026-01-15",
                        "source": "fixture",
                        "category": "company_announcement",
                        "title": "Fixture announcement",
                        "url": "https://example.test/fixture-announcement",
                        "summary": "Fixture-backed announcement.",
                        "risk_tags": [],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            records = JsonlInformationFetcher(fixture_path).fetch(
                "000001",
                None,
                date(2026, 1, 1),
                date(2026, 1, 31),
            )

            self.assertEqual([record.title for record in records], ["Fixture announcement"])

    def test_akshare_notice_fetcher_maps_notice_rows(self) -> None:
        from fintech_quant.information import AkShareNoticeFetcher, InformationCategory

        def fetcher() -> list[dict[str, object]]:
            return [
                {
                    "代码": "000001",
                    "公告日期": "20260603",
                    "公告标题": "Annual report released",
                    "公告类型": "年度报告",
                    "公告链接": "https://example.test/notice",
                }
            ]

        records = AkShareNoticeFetcher(report_type="财务报告", fetcher=fetcher).fetch(
            "000001",
            None,
            date(2026, 6, 1),
            date(2026, 6, 30),
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].normalized_symbol, "000001.SZ")
        self.assertEqual(records[0].published_at, date(2026, 6, 3))
        self.assertEqual(records[0].category, InformationCategory.FINANCIAL_REPORT)
        self.assertEqual(records[0].url, "https://example.test/notice")

    def test_akshare_notice_fetcher_reads_multiple_recent_pages(self) -> None:
        from fintech_quant.information import AkShareNoticeFetcher

        calls: list[int] = []

        def page_fetcher(page: int) -> list[dict[str, object]]:
            calls.append(page)
            return [
                {
                    "代码": "000001",
                    "公告日期": f"2026060{page}",
                    "公告标题": f"Notice page {page}",
                    "公告类型": "重大事项",
                    "公告链接": f"https://example.test/notice-{page}",
                }
            ]

        records = AkShareNoticeFetcher(
            recent_page=1,
            recent_pages=3,
            page_fetcher=page_fetcher,
        ).fetch(
            "000001",
            None,
            date(2026, 6, 1),
            date(2026, 6, 30),
        )

        self.assertEqual(calls, [1, 2, 3])
        self.assertEqual([record.title for record in records], ["Notice page 1", "Notice page 2", "Notice page 3"])

    def test_akshare_notice_fetcher_wraps_fetch_failures(self) -> None:
        from fintech_quant.data.errors import ProviderFetchError
        from fintech_quant.information import AkShareNoticeFetcher

        def fetcher() -> list[dict[str, object]]:
            raise RuntimeError("upstream timeout")

        with self.assertRaisesRegex(ProviderFetchError, "akshare notice"):
            AkShareNoticeFetcher(fetcher=fetcher).fetch(
                None,
                None,
                date(2026, 6, 1),
                date(2026, 6, 30),
            )

    def test_akshare_notice_fetcher_wraps_malformed_notice_rows(self) -> None:
        from fintech_quant.data.errors import ProviderFetchError
        from fintech_quant.information import AkShareNoticeFetcher

        def fetcher() -> list[dict[str, object]]:
            return [{"代码": "000001", "公告日期": "bad-date", "公告标题": "Broken row"}]

        with self.assertRaisesRegex(ProviderFetchError, "akshare notice"):
            AkShareNoticeFetcher(fetcher=fetcher).fetch(
                None,
                None,
                date(2026, 6, 1),
                date(2026, 6, 30),
            )

    def test_akshare_policy_news_fetcher_maps_sector_policy_rows(self) -> None:
        from fintech_quant.information import AkSharePolicyNewsFetcher, InformationCategory

        def fetcher() -> list[dict[str, object]]:
            return [
                {
                    "标题": "证监会加强新能源行业信息披露监管",
                    "发布时间": "2026-06-20 09:30:00",
                    "内容": "监管部门要求新能源上市公司提高财报透明度。",
                    "链接": "https://example.test/policy",
                },
                {
                    "标题": "消费行业景气修复",
                    "发布时间": "2026-06-20 10:00:00",
                    "内容": "消费行业新闻。",
                    "链接": "https://example.test/other",
                },
            ]

        records = AkSharePolicyNewsFetcher(fetcher=fetcher).fetch(
            None,
            "新能源",
            date(2026, 6, 1),
            date(2026, 6, 30),
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].category, InformationCategory.REGULATORY_POLICY)
        self.assertEqual(records[0].sector, "新能源")
        self.assertEqual(records[0].published_at, date(2026, 6, 20))
        self.assertEqual(records[0].url, "https://example.test/policy")
        self.assertIn("policy_pressure", records[0].risk_tags)
        self.assertIn("regulatory_risk", records[0].risk_tags)

    def test_akshare_policy_news_fetcher_uses_current_api_name(self) -> None:
        from fintech_quant.information import AkSharePolicyNewsFetcher

        calls: list[str] = []

        class FakeAkShare:
            @staticmethod
            def stock_info_global_cls(symbol: str):
                calls.append(symbol)
                return [
                    {
                        "标题": "监管部门完善资本市场制度",
                        "发布时间": "2026-06-23 12:00:00",
                        "内容": "政策监管新闻。",
                        "链接": "https://example.test/global",
                    }
                ]

        original_akshare = sys.modules.get("akshare")
        sys.modules["akshare"] = FakeAkShare()
        try:
            records = AkSharePolicyNewsFetcher().fetch(
                None,
                None,
                date(2026, 6, 23),
                date(2026, 6, 23),
            )
        finally:
            if original_akshare is None:
                sys.modules.pop("akshare", None)
            else:
                sys.modules["akshare"] = original_akshare

        self.assertEqual(calls, ["全部"])
        self.assertEqual(len(records), 1)

    def test_akshare_policy_news_fetcher_requires_symbol_and_sector_scope(self) -> None:
        from fintech_quant.information import AkSharePolicyNewsFetcher

        def fetcher() -> list[dict[str, object]]:
            return [
                {
                    "标题": "监管部门关注000001信息披露",
                    "发布时间": "2026-06-20 09:30:00",
                    "内容": "银行上市公司公告监管新闻。",
                    "链接": "https://example.test/bank",
                }
            ]

        records = AkSharePolicyNewsFetcher(fetcher=fetcher).fetch(
            "000001",
            "新能源",
            date(2026, 6, 1),
            date(2026, 6, 30),
        )

        self.assertEqual(records, [])

    def test_akshare_policy_news_fetcher_does_not_mark_neutral_regulation_negative(self) -> None:
        from fintech_quant.information import AkSharePolicyNewsFetcher

        def fetcher() -> list[dict[str, object]]:
            return [
                {
                    "标题": "监管部门完善新能源行业信息披露制度",
                    "发布时间": "2026-06-20 09:30:00",
                    "内容": "政策支持上市公司提高透明度。",
                    "链接": "https://example.test/neutral",
                }
            ]

        records = AkSharePolicyNewsFetcher(fetcher=fetcher).fetch(
            None,
            "新能源",
            date(2026, 6, 1),
            date(2026, 6, 30),
        )

        self.assertEqual(len(records), 1)
        self.assertIn("regulatory_policy", records[0].risk_tags)
        self.assertNotIn("regulatory_risk", records[0].risk_tags)

    def test_akshare_fund_flow_fetcher_maps_selected_stock_data(self) -> None:
        from fintech_quant.information import AkShareFundFlowFetcher, InformationCategory

        def fetcher(symbol: str, market: str) -> list[dict[str, object]]:
            self.assertEqual(symbol, "000001")
            self.assertEqual(market, "sz")
            return [
                {
                    "日期": "2026-06-03",
                    "主力净流入": "1200",
                    "收盘价": "10.5",
                    "涨跌幅": "1.2",
                }
            ]

        records = AkShareFundFlowFetcher(fetcher=fetcher).fetch(
            "000001",
            None,
            date(2026, 6, 1),
            date(2026, 6, 30),
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].category, InformationCategory.STOCK_DATA)
        self.assertEqual(records[0].normalized_symbol, "000001.SZ")
        self.assertEqual(records[0].published_at, date(2026, 6, 3))
        self.assertIn("selected_universe", records[0].risk_tags)
        self.assertIn("capital_flow", records[0].risk_tags)
        self.assertIn("main_inflow", records[0].risk_tags)

    def test_akshare_fundamental_fetcher_maps_selected_stock_data(self) -> None:
        from fintech_quant.information import AkShareFundamentalFetcher, InformationCategory

        calls: list[str] = []

        def valuation_fetcher(symbol: str) -> list[dict[str, object]]:
            calls.append(f"valuation:{symbol}")
            return [
                {
                    "日期": "2026-06-03",
                    "市盈率": "18",
                    "市净率": "1.5",
                }
            ]

        def financial_fetcher(symbol: str) -> list[dict[str, object]]:
            calls.append(f"financial:{symbol}")
            return [
                {
                    "日期": "2026-06-03",
                    "净资产收益率": "16",
                    "主营业务收入增长率": "12",
                }
            ]

        records = AkShareFundamentalFetcher(
            valuation_fetcher=valuation_fetcher,
            financial_fetcher=financial_fetcher,
        ).fetch(
            "000001",
            None,
            date(2026, 6, 1),
            date(2026, 6, 30),
        )

        self.assertEqual(calls, ["valuation:000001", "financial:000001"])
        self.assertEqual(len(records), 2)
        valuation = next(record for record in records if record.metadata["record_kind"] == "valuation")
        financial = next(
            record for record in records if record.metadata["record_kind"] == "financial_indicator"
        )
        self.assertEqual(valuation.category, InformationCategory.STOCK_DATA)
        self.assertEqual(valuation.normalized_symbol, "000001.SZ")
        self.assertEqual(valuation.published_at, date(2026, 6, 3))
        self.assertEqual(valuation.metadata["available_date_source"], "row_date")
        self.assertIn("selected_universe", valuation.risk_tags)
        self.assertIn("fundamental", valuation.risk_tags)
        self.assertIn("pe=18.0", valuation.summary)
        self.assertIn("pb=1.5", valuation.summary)
        self.assertNotIn("roe=", valuation.summary)
        self.assertEqual(financial.metadata["report_period"], "2026-06-03")
        self.assertEqual(financial.metadata["availability_verified"], False)
        self.assertIn("unverified_availability", financial.risk_tags)
        self.assertNotIn("fundamental", financial.risk_tags)
        self.assertIn("roe=0.16", financial.summary)
        self.assertIn("growth=0.12", financial.summary)

    def test_akshare_financial_statement_fetcher_maps_three_statement_rows(self) -> None:
        from fintech_quant.information import AkShareFinancialStatementFetcher, InformationCategory

        calls: list[tuple[str, str]] = []

        def fetcher(stock: str, statement_type: str) -> list[dict[str, object]]:
            calls.append((stock, statement_type))
            return [
                {
                    "报告日": "2025-12-31",
                    "更新日期": "2026-03-20 T18:05:05",
                    "营业收入": "120000",
                    "净利润": "15000",
                    "商誉": "3000",
                }
            ]

        records = AkShareFinancialStatementFetcher(fetcher=fetcher).fetch(
            "000001",
            None,
            date(2025, 1, 1),
            date(2026, 3, 31),
        )

        self.assertEqual(
            calls,
            [
                ("sz000001", "资产负债表"),
                ("sz000001", "利润表"),
                ("sz000001", "现金流量表"),
            ],
        )
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0].category, InformationCategory.STOCK_DATA)
        self.assertIn("selected_universe", records[0].risk_tags)
        self.assertIn("financial_statement", records[0].risk_tags)
        self.assertEqual(records[0].published_at, date(2026, 3, 20))
        self.assertEqual(records[0].metadata["statement_type"], "资产负债表")
        self.assertEqual(records[0].metadata["report_period"], "2025-12-31")
        self.assertEqual(records[0].metadata["available_date_source"], "更新日期")
        self.assertEqual(records[0].metadata["raw_row"]["营业收入"], "120000")
        self.assertIn("revenue=120000", records[1].summary)

    def test_akshare_financial_statement_fetcher_fails_without_public_availability_date(self) -> None:
        from fintech_quant.data.errors import ProviderFetchError
        from fintech_quant.information import AkShareFinancialStatementFetcher

        fetcher = AkShareFinancialStatementFetcher(
            statement_types=("资产负债表",),
            fetcher=lambda stock, statement_type: [{"报告日": "2025-12-31", "商誉": "3000"}],
        )

        with self.assertRaisesRegex(ProviderFetchError, "financial-statement fetch failed"):
            fetcher.fetch(
                "000001",
                None,
                date(2025, 1, 1),
                date(2026, 3, 31),
            )

    def test_akshare_pledge_ratio_fetcher_maps_selected_stock_data(self) -> None:
        from fintech_quant.information import AkSharePledgeRatioFetcher, InformationCategory

        def fetcher() -> list[dict[str, object]]:
            return [
                {"证券代码": "000001", "质押比例": "51%", "股票简称": "Ping An"},
                {"证券代码": "000002", "质押比例": "10%", "股票简称": "Other"},
            ]

        records = AkSharePledgeRatioFetcher(
            fetcher=fetcher,
            as_of=date(2026, 6, 30),
        ).fetch("000001", None, date(2026, 6, 1), date(2026, 6, 30))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].category, InformationCategory.STOCK_DATA)
        self.assertEqual(records[0].published_at, date(2026, 6, 30))
        self.assertIn("selected_universe", records[0].risk_tags)
        self.assertIn("pledge_ratio", records[0].risk_tags)
        self.assertEqual(records[0].summary, "pledge_ratio=0.51")

    def test_akshare_st_status_fetcher_maps_stock_name_warning(self) -> None:
        from fintech_quant.information import AkShareStStatusFetcher, InformationCategory

        def fetcher() -> list[dict[str, object]]:
            return [
                {"代码": "000001", "名称": "*ST平安"},
                {"代码": "000002", "名称": "万科A"},
            ]

        records = AkShareStStatusFetcher(fetcher=fetcher, as_of=date(2026, 6, 30)).fetch(
            "000001",
            None,
            date(2026, 6, 1),
            date(2026, 6, 30),
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].category, InformationCategory.STOCK_DATA)
        self.assertEqual(records[0].summary, "st_warning=true; stock_name=*ST平安")
        self.assertIn("selected_universe", records[0].risk_tags)
        self.assertIn("st_warning", records[0].risk_tags)

    def test_akshare_fundamental_fetcher_uses_current_api_names(self) -> None:
        from fintech_quant.information import AkShareFundamentalFetcher

        calls: list[str] = []

        class FakeAkShare:
            @staticmethod
            def stock_zh_a_spot_em():
                calls.append("valuation:spot")
                return [{"代码": "000001", "市盈率-动态": "18", "市净率": "1.5"}]

            @staticmethod
            def stock_financial_analysis_indicator(symbol: str):
                calls.append(f"financial:{symbol}")
                return [{"日期": "2026-06-03", "净资产收益率": "16", "主营业务收入增长率": "12"}]

        original_akshare = sys.modules.get("akshare")
        sys.modules["akshare"] = FakeAkShare()
        try:
            records = AkShareFundamentalFetcher().fetch(
                "000001",
                None,
                date(2026, 6, 1),
                date(2026, 6, 30),
            )
        finally:
            if original_akshare is None:
                sys.modules.pop("akshare", None)
            else:
                sys.modules["akshare"] = original_akshare

        self.assertEqual(calls, ["valuation:spot", "financial:000001"])
        self.assertGreaterEqual(len(records), 1)

    def test_akshare_fundamental_fetcher_keeps_partial_valuation_rows(self) -> None:
        from fintech_quant.information import AkShareFundamentalFetcher

        def valuation_fetcher(symbol: str) -> list[dict[str, object]]:
            return [{"日期": "2026-06-03", "市盈率": "18", "市净率": "1.5"}]

        def financial_fetcher(symbol: str) -> list[dict[str, object]]:
            raise RuntimeError("financial endpoint timeout")

        records = AkShareFundamentalFetcher(
            valuation_fetcher=valuation_fetcher,
            financial_fetcher=financial_fetcher,
        ).fetch(
            "000001",
            None,
            date(2026, 6, 1),
            date(2026, 6, 30),
        )

        self.assertEqual(len(records), 1)
        self.assertIn("pe=18.0", records[0].summary)
        self.assertIn("pb=1.5", records[0].summary)
        self.assertNotIn("roe=", records[0].summary)

    def test_akshare_fundamental_fetcher_dates_realtime_valuation_at_fetch_date(self) -> None:
        from fintech_quant.information import AkShareFundamentalFetcher

        def valuation_fetcher(symbol: str) -> list[dict[str, object]]:
            return [{"代码": "000001", "市盈率-动态": "18", "市净率": "1.5"}]

        def financial_fetcher(symbol: str) -> list[dict[str, object]]:
            raise RuntimeError("financial endpoint timeout")

        records = AkShareFundamentalFetcher(
            valuation_fetcher=valuation_fetcher,
            financial_fetcher=financial_fetcher,
            as_of=date(2026, 6, 30),
        ).fetch(
            "000001",
            None,
            date(2026, 6, 1),
            date(2026, 6, 30),
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].published_at, date(2026, 6, 30))
        self.assertEqual(records[0].metadata["available_date_source"], "fetch_date")

    def test_akshare_fundamental_fetcher_skips_empty_metric_rows(self) -> None:
        from fintech_quant.information import AkShareFundamentalFetcher

        def valuation_fetcher(symbol: str) -> list[dict[str, object]]:
            return [{"日期": "2026-06-03", "市盈率": "", "市净率": "nan"}]

        def financial_fetcher(symbol: str) -> list[dict[str, object]]:
            return [{"日期": "2026-06-03", "净资产收益率": "", "主营业务收入增长率": ""}]

        records = AkShareFundamentalFetcher(
            valuation_fetcher=valuation_fetcher,
            financial_fetcher=financial_fetcher,
        ).fetch(
            "000001",
            None,
            date(2026, 6, 1),
            date(2026, 6, 30),
        )

        self.assertEqual(records, [])

    def test_akshare_fundamental_fetcher_reports_both_endpoint_failures(self) -> None:
        from fintech_quant.data.errors import ProviderFetchError
        from fintech_quant.information import AkShareFundamentalFetcher

        def valuation_fetcher(symbol: str) -> list[dict[str, object]]:
            raise RuntimeError("valuation endpoint timeout")

        def financial_fetcher(symbol: str) -> list[dict[str, object]]:
            raise RuntimeError("financial endpoint timeout")

        with self.assertRaisesRegex(ProviderFetchError, "valuation endpoint timeout"):
            AkShareFundamentalFetcher(
                valuation_fetcher=valuation_fetcher,
                financial_fetcher=financial_fetcher,
            ).fetch(
                "000001",
                None,
                date(2026, 6, 1),
                date(2026, 6, 30),
            )

    def test_akshare_margin_fetcher_maps_margin_financing_rows(self) -> None:
        from fintech_quant.information import AkShareMarginFetcher, InformationCategory

        def fetcher(trade_date: date, market: str) -> list[dict[str, object]]:
            self.assertEqual(market, "sh")
            return [
                {
                    "信用交易日期": trade_date.isoformat(),
                    "标的证券代码": "600000",
                    "融资余额": "1000",
                    "融券余量": "20",
                }
            ]

        records = AkShareMarginFetcher(fetcher=fetcher).fetch(
            "600000",
            None,
            date(2026, 6, 3),
            date(2026, 6, 3),
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].category, InformationCategory.STOCK_DATA)
        self.assertEqual(records[0].normalized_symbol, "600000.SH")
        self.assertIn("selected_universe", records[0].risk_tags)
        self.assertIn("margin_financing", records[0].risk_tags)

    def test_akshare_dragon_tiger_fetcher_maps_sentiment_rows(self) -> None:
        from fintech_quant.information import AkShareDragonTigerFetcher, InformationCategory

        def fetcher(window: str) -> list[dict[str, object]]:
            self.assertEqual(window, "5")
            return [
                {
                    "代码": "000001",
                    "名称": "平安银行",
                    "上榜次数": "2",
                    "累积购买额": "2000",
                    "累积卖出额": "1500",
                    "净额": "500",
                }
            ]

        records = AkShareDragonTigerFetcher(as_of=date(2026, 6, 23), fetcher=fetcher).fetch(
            "000001",
            None,
            date(2026, 6, 1),
            date(2026, 6, 30),
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].category, InformationCategory.MARKET_SENTIMENT)
        self.assertEqual(records[0].normalized_symbol, "000001.SZ")
        self.assertEqual(records[0].published_at, date(2026, 6, 23))
        self.assertIn("dragon_tiger", records[0].risk_tags)
        self.assertIn("dragon_tiger_positive", records[0].risk_tags)

    def test_akshare_dragon_tiger_fetcher_uses_current_api_name(self) -> None:
        from fintech_quant.information import AkShareDragonTigerFetcher

        calls: list[str] = []

        class FakeAkShare:
            @staticmethod
            def stock_lhb_ggtj_sina(symbol: str):
                calls.append(symbol)
                return [
                    {
                        "代码": "000001",
                        "名称": "平安银行",
                        "上榜次数": "1",
                        "净额": "100",
                    }
                ]

        original_akshare = sys.modules.get("akshare")
        sys.modules["akshare"] = FakeAkShare()
        try:
            records = AkShareDragonTigerFetcher(as_of=date(2026, 6, 23)).fetch(
                "000001",
                None,
                date(2026, 6, 23),
                date(2026, 6, 23),
            )
        finally:
            if original_akshare is None:
                sys.modules.pop("akshare", None)
            else:
                sys.modules["akshare"] = original_akshare

        self.assertEqual(calls, ["5"])
        self.assertEqual(len(records), 1)

    def test_akshare_dragon_tiger_fetcher_does_not_backfill_historical_ranges(self) -> None:
        from fintech_quant.information import AkShareDragonTigerFetcher

        def fetcher(window: str) -> list[dict[str, object]]:
            return [
                {
                    "代码": "000001",
                    "名称": "平安银行",
                    "上榜次数": "1",
                    "净额": "100",
                }
            ]

        records = AkShareDragonTigerFetcher(as_of=date(2026, 6, 23), fetcher=fetcher).fetch(
            "000001",
            None,
            date(2026, 6, 1),
            date(2026, 6, 10),
        )

        self.assertEqual(records, [])

    def test_combined_information_fetcher_merges_multiple_sources(self) -> None:
        from fintech_quant.information import CombinedInformationFetcher, InformationCategory, InformationRecord, StaticInformationFetcher

        first = StaticInformationFetcher(
            [
                InformationRecord(
                    symbol="000001",
                    sector=None,
                    published_at=date(2026, 6, 1),
                    source="fixture_one",
                    category=InformationCategory.COMPANY_ANNOUNCEMENT,
                    title="Announcement",
                    url="",
                    summary="Announcement row.",
                    risk_tags=(),
                )
            ]
        )
        second = StaticInformationFetcher(
            [
                InformationRecord(
                    symbol="000001",
                    sector=None,
                    published_at=date(2026, 6, 2),
                    source="fixture_two",
                    category=InformationCategory.MARKET_SENTIMENT,
                    title="Sentiment",
                    url="",
                    summary="Sentiment row.",
                    risk_tags=(),
                )
            ]
        )

        records = CombinedInformationFetcher([second, first]).fetch("000001", None, date(2026, 6, 1), date(2026, 6, 30))

        self.assertEqual([record.title for record in records], ["Announcement", "Sentiment"])

    def test_combined_information_fetcher_can_ignore_optional_source_failures(self) -> None:
        from fintech_quant.data.errors import ProviderFetchError
        from fintech_quant.information import CombinedInformationFetcher, InformationCategory, InformationRecord, StaticInformationFetcher

        class FailingFetcher:
            def fetch(self, symbol, sector, start, end):
                raise ProviderFetchError("optional source failed")

        stable = StaticInformationFetcher(
            [
                InformationRecord(
                    symbol="000001",
                    sector=None,
                    published_at=date(2026, 6, 1),
                    source="fixture",
                    category=InformationCategory.COMPANY_ANNOUNCEMENT,
                    title="Stable",
                    url="",
                    summary="Stable source.",
                    risk_tags=(),
                )
            ]
        )

        records = CombinedInformationFetcher([FailingFetcher(), stable], ignore_fetch_errors=True).fetch(
            "000001",
            None,
            date(2026, 6, 1),
            date(2026, 6, 30),
        )

        self.assertEqual([record.title for record in records], ["Stable"])

    def test_fetch_information_help_includes_akshare_multi_source(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)

        result = subprocess.run(
            [sys.executable, "scripts/fetch_information.py", "--help"],
            cwd=worktree,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("akshare_multi", result.stdout)
        self.assertIn("akshare_policy", result.stdout)
        self.assertIn("akshare_fundamental", result.stdout)
        self.assertIn("akshare_financial_statement", result.stdout)
        self.assertIn("akshare_pledge_ratio", result.stdout)
        self.assertIn("akshare_st_status", result.stdout)
        self.assertIn("akshare_financial_report", result.stdout)
        self.assertIn("--recent-pages", result.stdout)

    def test_fetch_information_help_describes_recent_page_as_page_bounded(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)

        result = subprocess.run(
            [sys.executable, "scripts/fetch_information.py", "--help"],
            cwd=worktree,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("--recent-page", result.stdout)
        self.assertIn("--recent-pages", result.stdout)
        self.assertIn("Number of AkShare notice pages", result.stdout)
        self.assertIn("--retention-as-of", result.stdout)

    def test_static_fetcher_normalizes_non_empty_symbol_filter(self) -> None:
        from fintech_quant.information import InformationCategory, InformationRecord, StaticInformationFetcher

        record = InformationRecord(
            symbol="000001",
            sector="banking",
            published_at=date(2026, 1, 15),
            source="exchange",
            category=InformationCategory.COMPANY_ANNOUNCEMENT,
            title="Normalized symbol match",
            url="https://example.test/normalized",
            summary="Matches normalized filter.",
            risk_tags=(),
        )
        fetcher = StaticInformationFetcher(records=[record])

        by_raw_symbol = fetcher.fetch("000001", None, date(2026, 1, 1), date(2026, 1, 31))
        by_normalized_symbol = fetcher.fetch("000001.SZ", None, date(2026, 1, 1), date(2026, 1, 31))

        self.assertEqual([item.title for item in by_raw_symbol], ["Normalized symbol match"])
        self.assertEqual([item.title for item in by_normalized_symbol], ["Normalized symbol match"])

    def test_static_fetcher_supports_positional_fetch_arguments(self) -> None:
        from fintech_quant.information import InformationCategory, InformationRecord, StaticInformationFetcher

        record = InformationRecord(
            symbol="000001",
            sector="banking",
            published_at=date(2026, 1, 15),
            source="exchange",
            category=InformationCategory.COMPANY_ANNOUNCEMENT,
            title="Positional fetch",
            url="https://example.test/positional",
            summary="Positional arguments work.",
            risk_tags=(),
        )
        fetcher = StaticInformationFetcher(records=[record])

        records = fetcher.fetch(None, "banking", date(2026, 1, 1), date(2026, 1, 31))

        self.assertEqual([item.title for item in records], ["Positional fetch"])


if __name__ == "__main__":
    unittest.main()
