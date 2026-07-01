from __future__ import annotations

import unittest
from datetime import date


class ResearchScoringTest(unittest.TestCase):
    def test_build_score_input_maps_feature_fundamental_capital_and_information(self) -> None:
        from fintech_quant.information import InformationCategory, InformationRecord
        from fintech_quant.research.dataset import FeatureRow, SupplementalRow
        from fintech_quant.research.scoring import build_score_input

        feature_row = FeatureRow(
            symbol="000001.SZ",
            trade_date=date(2026, 1, 2),
            values={
                "symbol": "000001.SZ",
                "trade_date": date(2026, 1, 2),
                "close_above_ma20": True,
                "close_above_ma60": True,
                "rsi14": 55.0,
                "macd_positive": True,
                "volume": 1000.0,
                "return_1d": 0.01,
            },
        )
        fundamentals = SupplementalRow(
            symbol="000001.SZ",
            trade_date=None,
            values={"pe": 18.0, "pb": 1.5, "roe": 0.16, "growth": 0.12},
        )
        capital_flow = SupplementalRow(
            symbol="000001.SZ",
            trade_date=date(2026, 1, 2),
            values={"main_net_inflow": -1000.0, "main_outflow_days": 4, "margin_financing_positive": False},
        )
        negative_record = InformationRecord(
            symbol="000001",
            sector=None,
            published_at=date(2026, 1, 1),
            source="fixture",
            category=InformationCategory.COMPANY_ANNOUNCEMENT,
            title="Risk notice",
            url="https://example.test/risk",
            summary="Risk fixture.",
            risk_tags=("negative_announcement",),
        )

        score_input = build_score_input(feature_row, fundamentals, capital_flow, [negative_record])

        self.assertEqual(score_input.symbol, "000001.SZ")
        self.assertEqual(score_input.pe, 18.0)
        self.assertEqual(score_input.close_above_ma20, True)
        self.assertEqual(score_input.rsi, 55.0)
        self.assertEqual(score_input.main_outflow_days, 4)
        self.assertEqual(score_input.negative_event_count, 1)
        self.assertEqual(score_input.volume_confirmed, True)

    def test_build_score_input_counts_sector_negative_information(self) -> None:
        from fintech_quant.information import InformationCategory, InformationRecord
        from fintech_quant.research.dataset import FeatureRow
        from fintech_quant.research.scoring import build_score_input

        feature_row = FeatureRow(
            symbol="000001.SZ",
            trade_date=date(2026, 1, 2),
            values={
                "symbol": "000001.SZ",
                "sector": "新能源",
                "trade_date": date(2026, 1, 2),
                "volume": 1000.0,
                "return_1d": 0.01,
            },
        )
        sector_record = InformationRecord(
            symbol=None,
            sector="新能源",
            published_at=date(2026, 1, 1),
            source="fixture",
            category=InformationCategory.REGULATORY_POLICY,
            title="Sector regulatory pressure",
            url="https://example.test/policy",
            summary="Sector policy fixture.",
            risk_tags=("regulatory_risk",),
        )

        score_input = build_score_input(feature_row, information_records=[sector_record])

        self.assertEqual(score_input.negative_event_count, 1)

    def test_build_stock_scores_preserves_required_components(self) -> None:
        from fintech_quant.research.dataset import FeatureRow, ResearchDataset, SupplementalRow
        from fintech_quant.research.scoring import build_stock_scores

        dataset = ResearchDataset(
            features=[
                FeatureRow(
                    symbol="000001.SZ",
                    trade_date=date(2026, 1, 1),
                    values={
                        "symbol": "000001.SZ",
                        "trade_date": date(2026, 1, 1),
                        "close_above_ma20": True,
                        "close_above_ma60": True,
                        "rsi14": 55.0,
                        "macd_positive": True,
                        "volume": 1000.0,
                        "return_1d": 0.01,
                    },
                )
            ],
            fundamentals={
                ("000001.SZ", None): SupplementalRow(
                    "000001.SZ",
                    None,
                    {"pe": 18.0, "pb": 1.5, "roe": 0.16, "growth": 0.12},
                )
            },
            capital_flow={
                ("000001.SZ", date(2026, 1, 1)): SupplementalRow(
                    "000001.SZ",
                    date(2026, 1, 1),
                    {"main_net_inflow": 1000.0, "main_outflow_days": 0, "margin_financing_positive": True},
                )
            },
            market_state={},
            information_records=[],
            universe_symbols=("000001.SZ",),
        )

        scores = build_stock_scores(dataset)
        score = scores[(date(2026, 1, 1), "000001.SZ")]

        self.assertIn("fundamental", score.components)
        self.assertIn("technical", score.components)
        self.assertIn("capital_flow", score.components)
        self.assertIn("sentiment", score.components)
        self.assertEqual(score.symbol, "000001.SZ")


if __name__ == "__main__":
    unittest.main()
