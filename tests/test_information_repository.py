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
        self.assertIn("Date filtering is page-", result.stdout)
        self.assertIn("bounded to this page.", result.stdout)
        self.assertIn("--recent-page", result.stdout)
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
