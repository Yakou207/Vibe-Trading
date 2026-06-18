from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
