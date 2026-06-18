from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
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

    def test_non_selected_stock_data_is_pruned_by_text_policy(self) -> None:
        from fintech_quant.information import InformationCategory, InformationRecord, InformationRepository

        with tempfile.TemporaryDirectory() as tmp:
            repo = InformationRepository(Path(tmp) / "info.jsonl")
            old_stock_data = InformationRecord(
                symbol="000001",
                sector=None,
                published_at=date(2019, 1, 1),
                source="local",
                category=InformationCategory.STOCK_DATA,
                title="Non-selected training row",
                url="",
                summary="Should be pruned.",
                risk_tags=(),
            )

            repo.append(old_stock_data)
            removed = repo.prune_text_records(today=date(2026, 6, 18))

            self.assertEqual(removed, 1)
            self.assertEqual(repo.query(symbol="000001"), [])

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

    def test_fetch_information_script_runs_without_manual_pythonpath(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [
                sys.executable,
                "scripts/fetch_information.py",
                "--start",
                "2026-01-01",
                "--end",
                "2026-01-31",
            ],
            cwd=worktree,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "stored_records=0")
        self.assertEqual(result.stderr, "")

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
