from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


class FinancialReportArchiveTest(unittest.TestCase):
    def test_information_repository_round_trips_record_metadata(self) -> None:
        from fintech_quant.information import InformationCategory, InformationRecord, InformationRepository

        with tempfile.TemporaryDirectory() as tmp:
            repo = InformationRepository(Path(tmp) / "information.jsonl")
            repo.append(
                InformationRecord(
                    symbol="000001",
                    sector=None,
                    published_at=date(2026, 4, 30),
                    source="fixture",
                    category=InformationCategory.FINANCIAL_REPORT,
                    title="2025 annual report",
                    url="https://example.test/report.html",
                    summary="年度报告",
                    risk_tags=("financial_report",),
                    metadata={"raw_text_path": "data/raw/information/reports/000001/report.txt"},
                )
            )

            records = repo.query(symbol="000001", category=InformationCategory.FINANCIAL_REPORT)

        self.assertEqual(records[0].metadata["raw_text_path"], "data/raw/information/reports/000001/report.txt")

    def test_archive_financial_reports_script_extracts_html_text_and_updates_metadata(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html_path = root / "annual_report.html"
            input_path = root / "information.jsonl"
            output_path = root / "archived_information.jsonl"
            document_root = root / "documents"
            html_path.write_text(
                "<html><body><h1>Annual Report</h1><p>Revenue grew 18 percent.</p></body></html>",
                encoding="utf-8",
            )
            input_path.write_text(
                json.dumps(
                    {
                        "symbol": "000001.SZ",
                        "sector": None,
                        "published_at": "2026-04-30",
                        "source": "akshare_notice",
                        "category": "financial_report",
                        "title": "2025 annual report",
                        "url": html_path.as_uri(),
                        "summary": "年度报告",
                        "risk_tags": ["financial_report"],
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
                    "scripts/archive_financial_reports.py",
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--document-root",
                    str(document_root),
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            archived_record = json.loads(output_path.read_text(encoding="utf-8"))
            text_path = Path(str(archived_record["metadata"]["raw_text_path"]))
            extracted_text = text_path.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "archived_financial_reports=1\nwritten_records=1")
        self.assertEqual(archived_record["metadata"]["archive_status"], "archived")
        self.assertIn("Revenue grew 18 percent.", extracted_text)


if __name__ == "__main__":
    unittest.main()
