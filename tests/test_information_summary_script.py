from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class InformationSummaryScriptTest(unittest.TestCase):
    def test_summary_script_reports_category_risk_and_recent_negative_records(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "information.jsonl"
            output_path = root / "summary.json"
            input_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "symbol": "000001.SZ",
                                "sector": None,
                                "published_at": "2026-01-02",
                                "source": "fixture",
                                "category": "company_announcement",
                                "title": "监管问询",
                                "url": "",
                                "summary": "公司收到监管问询。",
                                "risk_tags": ["negative_text_sentiment"],
                                "metadata": {
                                    "negative_keywords": ["问询"],
                                    "raw_document_path": "data/raw/information/financial_reports/report.html",
                                    "raw_text_path": "data/raw/information/financial_reports/report.txt",
                                    "text_chars": 120,
                                    "text_sentiment_score": -1.0,
                                },
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        json.dumps(
                            {
                                "symbol": "000001.SZ",
                                "sector": None,
                                "published_at": "2026-01-03",
                                "source": "fixture",
                                "category": "stock_data",
                                "title": "基本面",
                                "url": "",
                                "summary": "pe=12.0; pb=1.2",
                                "risk_tags": ["selected_universe", "fundamental"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        json.dumps(
                            {
                                "symbol": None,
                                "sector": "银行",
                                "published_at": "2026-01-04",
                                "source": "fixture",
                                "category": "regulatory_policy",
                                "title": "银行政策",
                                "url": "",
                                "summary": "监管政策更新。",
                                "risk_tags": ["regulatory_policy"],
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
                    "scripts/summarize_information_repository.py",
                    "--input",
                    str(input_path),
                    "--symbol",
                    "000001",
                    "--sector",
                    "银行",
                    "--as-of",
                    "2026-01-05",
                    "--recent-days",
                    "7",
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
        self.assertIn(f"summary_path={output_path}", result.stdout)
        self.assertEqual(payload["record_count"], 3)
        self.assertEqual(payload["category_counts"]["company_announcement"], 1)
        self.assertEqual(payload["category_counts"]["stock_data"], 1)
        self.assertEqual(payload["retention_counts"]["selected_universe_stock_data"], 1)
        self.assertEqual(payload["risk_tag_counts"]["negative_text_sentiment"], 1)
        self.assertEqual(payload["negative_record_count"], 1)
        self.assertEqual(payload["archive_summary"]["archived_document_count"], 1)
        self.assertEqual(payload["archive_summary"]["extracted_text_count"], 1)
        self.assertEqual(payload["archive_summary"]["total_text_chars"], 120)
        self.assertEqual(payload["keyword_counts"]["negative"]["问询"], 1)
        self.assertEqual(payload["recent_negative_records"][0]["title"], "监管问询")

    def test_summary_script_reports_retention_symbol_and_sector_analysis(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "information.jsonl"
            output_path = root / "summary.json"
            input_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "symbol": "000001.SZ",
                                "sector": "银行",
                                "published_at": "2026-01-02",
                                "source": "exchange",
                                "category": "financial_report",
                                "title": "2025年报",
                                "url": "",
                                "summary": "营收增长。",
                                "risk_tags": ["financial_report"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        json.dumps(
                            {
                                "symbol": "000001.SZ",
                                "sector": "银行",
                                "published_at": "2026-01-03",
                                "source": "akshare",
                                "category": "stock_data",
                                "title": "训练数据",
                                "url": "",
                                "summary": "pe=12.0; pb=1.2",
                                "risk_tags": ["selected_universe", "fundamental"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        json.dumps(
                            {
                                "symbol": "000001.SZ",
                                "sector": "银行",
                                "published_at": "2026-01-04",
                                "source": "exchange",
                                "category": "company_announcement",
                                "title": "监管问询",
                                "url": "",
                                "summary": "公司收到问询。",
                                "risk_tags": ["negative_text_sentiment"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        json.dumps(
                            {
                                "symbol": None,
                                "sector": "银行",
                                "published_at": "2026-01-05",
                                "source": "regulator",
                                "category": "regulatory_policy",
                                "title": "银行政策",
                                "url": "",
                                "summary": "监管政策更新。",
                                "risk_tags": ["regulatory_policy"],
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
                    "scripts/summarize_information_repository.py",
                    "--input",
                    str(input_path),
                    "--as-of",
                    "2026-01-06",
                    "--recent-days",
                    "7",
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
        self.assertEqual(payload["retention_class_summary"]["text_financial_report"]["record_count"], 3)
        self.assertEqual(payload["retention_class_summary"]["selected_universe_stock_data"]["record_count"], 1)
        self.assertEqual(payload["by_symbol"]["000001.SZ"]["latest_financial_report_at"], "2026-01-02")
        self.assertEqual(payload["by_symbol"]["000001.SZ"]["latest_stock_data_at"], "2026-01-03")
        self.assertEqual(payload["by_symbol"]["000001.SZ"]["recent_negative_record_count"], 1)
        self.assertEqual(payload["by_symbol"]["000001.SZ"]["recent_negative_titles"], ["监管问询"])
        self.assertEqual(payload["by_sector"]["银行"]["record_count"], 4)
        self.assertEqual(payload["by_sector"]["银行"]["latest_policy_at"], "2026-01-05")
        self.assertEqual(payload["by_sector"]["银行"]["symbols"], ["000001.SZ"])


if __name__ == "__main__":
    unittest.main()
