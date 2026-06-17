from __future__ import annotations

import unittest

import pandas as pd


class AnalysisFrameworkContractsTest(unittest.TestCase):
    def test_fundamental_provider_contract_normalizes_records(self) -> None:
        from fintech_quant.data.fundamental_provider import FundamentalRecord, records_to_frame

        frame = records_to_frame(
            [
                FundamentalRecord(
                    symbol="sh688001",
                    date="2024-03-31",
                    pe=30.0,
                    pb=4.0,
                    roe=0.12,
                    revenue_growth=0.20,
                    profit_growth=0.10,
                    debt_ratio=0.30,
                )
            ]
        )

        self.assertEqual(
            list(frame.columns),
            [
                "代码",
                "date",
                "pe",
                "pb",
                "roe",
                "revenue_growth",
                "profit_growth",
                "debt_ratio",
            ],
        )

    def test_news_provider_contract_normalizes_records(self) -> None:
        from fintech_quant.data.news_provider import NewsRecord, records_to_frame

        frame = records_to_frame(
            [
                NewsRecord(
                    symbol="sh688001",
                    published_at="2024-01-02",
                    title="sample",
                    source="fixture",
                    url="https://example.com/news",
                )
            ]
        )

        self.assertEqual(list(frame.columns), ["代码", "published_at", "title", "source", "url"])

    def test_sentiment_and_nlp_features_create_structured_daily_factors(self) -> None:
        from fintech_quant.features.nlp import build_news_attention_features
        from fintech_quant.features.sentiment import build_daily_sentiment_features

        news = pd.DataFrame(
            {
                "代码": ["sh688001", "sh688001"],
                "published_at": ["2024-01-02", "2024-01-02"],
                "title": ["good growth", "risk warning"],
                "sentiment_score": [0.8, -0.4],
            }
        )

        sentiment = build_daily_sentiment_features(news)
        attention = build_news_attention_features(news)

        self.assertEqual(sentiment.loc[0, "sentiment_score_mean"], 0.2)
        self.assertEqual(sentiment.loc[0, "negative_news_ratio"], 0.5)
        self.assertEqual(attention.loc[0, "news_count"], 2)

    def test_factor_diagnostics_report_contract(self) -> None:
        from fintech_quant.features.factor_diagnostics import factor_diagnostics
        from fintech_quant.reports.factor_report import build_factor_report

        features = pd.DataFrame(
            {
                "代码": ["a", "b", "c"],
                "date": ["2024-01-02"] * 3,
                "factor_a": [1.0, 2.0, 3.0],
                "factor_b": [3.0, 2.0, 1.0],
                "target_next_return_1d": [0.01, 0.02, 0.03],
            }
        )

        diagnostics = factor_diagnostics(features, ["factor_a", "factor_b"])
        report = build_factor_report(diagnostics)

        self.assertEqual(report["report"], "factor_diagnostics")
        self.assertEqual(report["factor_count"], 2)
        self.assertIn("factor_a", report["factors"])
        self.assertEqual(report["factors"]["factor_a"]["rank_ic"], 1.0)
        self.assertEqual(report["factors"]["factor_b"]["rank_ic"], -1.0)
        self.assertIn("top_abs_ic", report)


if __name__ == "__main__":
    unittest.main()
