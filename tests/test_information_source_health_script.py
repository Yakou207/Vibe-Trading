from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class InformationSourceHealthScriptTest(unittest.TestCase):
    def test_health_script_reports_per_source_counts_and_errors(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.pop("TUSHARE_TOKEN", None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "information.jsonl"
            output_path = root / "health.json"
            input_path.write_text(
                json.dumps(
                    {
                        "symbol": "000001",
                        "sector": None,
                        "published_at": "2026-01-02",
                        "source": "fixture",
                        "category": "company_announcement",
                        "title": "Fixture announcement",
                        "url": "",
                        "summary": "Fixture.",
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
                    "scripts/check_information_sources.py",
                    "--sources",
                    "jsonl,tushare_fundamental",
                    "--input",
                    str(input_path),
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
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(f"health_report={output_path}", result.stdout)
        self.assertEqual(payload["summary"]["ok_sources"], 1)
        self.assertEqual(payload["summary"]["error_sources"], 1)
        self.assertEqual(payload["sources"][0]["source"], "jsonl")
        self.assertEqual(payload["sources"][0]["status"], "ok")
        self.assertEqual(payload["sources"][0]["record_count"], 1)
        self.assertEqual(payload["sources"][1]["source"], "tushare_fundamental")
        self.assertEqual(payload["sources"][1]["status"], "error")
        self.assertIn("TUSHARE_TOKEN", payload["sources"][1]["error"])

    def test_health_script_checks_selected_universe_symbols_and_sectors(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            input_path = root / "information.jsonl"
            output_path = root / "health.json"
            universe_path.write_text("symbol,name,sector\n000001,平安银行,银行\n", encoding="utf-8")
            input_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "symbol": "000001",
                                "sector": None,
                                "published_at": "2026-01-02",
                                "source": "fixture",
                                "category": "company_announcement",
                                "title": "个股公告",
                                "url": "",
                                "summary": "个股公告。",
                                "risk_tags": [],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        json.dumps(
                            {
                                "symbol": None,
                                "sector": "银行",
                                "published_at": "2026-01-02",
                                "source": "fixture",
                                "category": "regulatory_policy",
                                "title": "板块政策",
                                "url": "",
                                "summary": "板块政策。",
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
                    "scripts/check_information_sources.py",
                    "--sources",
                    "jsonl",
                    "--input",
                    str(input_path),
                    "--universe",
                    str(universe_path),
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
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(payload["summary"]["total_scopes"], 2)
        self.assertEqual(payload["summary"]["total_records"], 2)
        self.assertEqual(payload["scopes"][0]["symbol"], "000001.SZ")
        self.assertIsNone(payload["scopes"][0]["sector"])
        self.assertEqual(payload["scopes"][0]["sources"][0]["record_count"], 1)
        self.assertIsNone(payload["scopes"][1]["symbol"])
        self.assertEqual(payload["scopes"][1]["sector"], "银行")
        self.assertEqual(payload["scopes"][1]["sources"][0]["record_count"], 1)


if __name__ == "__main__":
    unittest.main()
