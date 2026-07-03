from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


class InformationSentimentTest(unittest.TestCase):
    def test_dictionary_sentiment_scores_negative_and_positive_text(self) -> None:
        from fintech_quant.information.sentiment import analyze_text_sentiment

        negative = analyze_text_sentiment("公司收到监管问询并提示退市风险。")
        positive = analyze_text_sentiment("公司业绩增长并获得政策支持。")

        self.assertLess(negative.score, 0.0)
        self.assertIn("问询", negative.negative_keywords)
        self.assertGreater(positive.score, 0.0)
        self.assertIn("增长", positive.positive_keywords)

    def test_analyze_information_sentiment_script_updates_records(self) -> None:
        worktree = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "information.jsonl"
            output_path = root / "analyzed.jsonl"
            input_path.write_text(
                json.dumps(
                    {
                        "symbol": "000001",
                        "sector": None,
                        "published_at": "2026-01-01",
                        "source": "fixture",
                        "category": "company_announcement",
                        "title": "监管问询",
                        "url": "",
                        "summary": "公司提示退市风险。",
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
                    "scripts/analyze_information_sentiment.py",
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            record = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "analyzed_records=1\nnegative_text_records=1")
        self.assertIn("negative_text_sentiment", record["risk_tags"])
        self.assertLess(record["metadata"]["text_sentiment_score"], 0.0)
        self.assertIn("退市", record["metadata"]["negative_keywords"])

    def test_text_sentiment_tag_counts_as_negative_information(self) -> None:
        from fintech_quant.information import InformationCategory, InformationRecord
        from fintech_quant.research.dataset import FeatureRow
        from fintech_quant.research.scoring import build_score_input

        feature_row = FeatureRow(
            symbol="000001.SZ",
            trade_date=date(2026, 1, 2),
            values={"symbol": "000001.SZ", "trade_date": date(2026, 1, 2)},
        )
        record = InformationRecord(
            symbol="000001",
            sector=None,
            published_at=date(2026, 1, 1),
            source="fixture",
            category=InformationCategory.COMPANY_ANNOUNCEMENT,
            title="Sentiment risk",
            url="",
            summary="Negative text sentiment.",
            risk_tags=("negative_text_sentiment",),
        )

        score_input = build_score_input(feature_row, information_records=[record])

        self.assertEqual(score_input.negative_event_count, 1)


if __name__ == "__main__":
    unittest.main()
