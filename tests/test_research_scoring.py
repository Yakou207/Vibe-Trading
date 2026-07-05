from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path


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
                "rs_rank_20d": 0.8,
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
        self.assertEqual(score_input.relative_strength, 0.8)
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

    def test_build_stock_scores_uses_information_fundamentals_loaded_into_dataset(self) -> None:
        from fintech_quant.research.dataset import FeatureRow, ResearchDataset, SupplementalRow
        from fintech_quant.research.scoring import build_stock_scores

        dataset = ResearchDataset(
            features=[
                FeatureRow(
                    symbol="000001.SZ",
                    trade_date=date(2026, 6, 3),
                    values={
                        "symbol": "000001.SZ",
                        "trade_date": date(2026, 6, 3),
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
                ("000001.SZ", date(2026, 6, 3)): SupplementalRow(
                    "000001.SZ",
                    date(2026, 6, 3),
                    {"pe": 18.0, "pb": 1.5, "roe": 0.16, "growth": 0.12},
                )
            },
            capital_flow={},
            market_state={},
            information_records=[],
            universe_symbols=("000001.SZ",),
        )

        score = build_stock_scores(dataset)[(date(2026, 6, 3), "000001.SZ")]

        self.assertEqual(score.components["fundamental"].score, 35.0)
        self.assertNotIn("pe", score.missing_fields)

    def test_build_stock_scores_uses_information_capital_flow_loaded_into_dataset(self) -> None:
        from fintech_quant.research.dataset import FeatureRow, ResearchDataset, SupplementalRow
        from fintech_quant.research.scoring import build_stock_scores

        dataset = ResearchDataset(
            features=[
                FeatureRow(
                    symbol="000001.SZ",
                    trade_date=date(2026, 6, 3),
                    values={
                        "symbol": "000001.SZ",
                        "trade_date": date(2026, 6, 3),
                        "close_above_ma20": True,
                        "close_above_ma60": True,
                        "rsi14": 55.0,
                        "macd_positive": True,
                        "volume": 1000.0,
                        "return_1d": 0.01,
                    },
                )
            ],
            fundamentals={},
            capital_flow={
                ("000001.SZ", date(2026, 6, 3)): SupplementalRow(
                    "000001.SZ",
                    date(2026, 6, 3),
                    {"main_net_inflow": 1000.0, "main_outflow_days": 0, "margin_financing_positive": True},
                )
            },
            market_state={},
            information_records=[],
            universe_symbols=("000001.SZ",),
        )

        score = build_stock_scores(dataset)[(date(2026, 6, 3), "000001.SZ")]

        self.assertEqual(score.components["capital_flow"].score, 25.0)
        self.assertNotIn("main_net_inflow", score.missing_fields)

    def test_build_stock_scores_uses_dragon_tiger_information_for_sentiment(self) -> None:
        from fintech_quant.information import InformationCategory, InformationRecord
        from fintech_quant.research.dataset import FeatureRow, ResearchDataset
        from fintech_quant.research.scoring import build_stock_scores

        dataset = ResearchDataset(
            features=[
                FeatureRow(
                    symbol="000001.SZ",
                    trade_date=date(2026, 6, 3),
                    values={
                        "symbol": "000001.SZ",
                        "trade_date": date(2026, 6, 3),
                        "limit_up_streak": 0,
                    },
                )
            ],
            fundamentals={},
            capital_flow={},
            market_state={},
            information_records=[
                InformationRecord(
                    symbol="000001",
                    sector=None,
                    published_at=date(2026, 6, 2),
                    source="akshare_dragon_tiger",
                    category=InformationCategory.MARKET_SENTIMENT,
                    title="dragon tiger",
                    url="",
                    summary="net_amount=1000.0",
                    risk_tags=("dragon_tiger", "dragon_tiger_positive"),
                )
            ],
            universe_symbols=("000001.SZ",),
        )

        score = build_stock_scores(dataset)[(date(2026, 6, 3), "000001.SZ")]

        self.assertEqual(score.components["sentiment"].score, 10.0)
        self.assertNotIn("dragon_tiger_positive", score.missing_fields)

    def test_explicit_dragon_tiger_feature_overrides_information_sentiment(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset
        from fintech_quant.research.scoring import build_stock_scores

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            features_path = root / "features.csv"
            information_path = root / "information.jsonl"
            universe_path.write_text("symbol,name,sector\n000001,Ping An,Bank\n", encoding="utf-8")
            features_path.write_text(
                "symbol,trade_date,open,high,low,close,volume,amount,source,return_1d,ma20,ma60,ma250,"
                "close_above_ma20,close_above_ma60,close_above_ma250,rsi14,macd_line,macd_signal,macd_hist,"
                "macd_positive,volatility20,limit_up_streak,dragon_tiger_positive\n"
                "000001,2026-06-03,10,10,10,10,1000,10000,fixture,0.01,9,8,7,true,true,true,55,"
                "0.1,0.05,0.05,true,0.02,0,false\n",
                encoding="utf-8",
            )
            information_path.write_text(
                '{"symbol": "000001", "sector": null, "published_at": "2026-06-02", '
                '"source": "akshare_dragon_tiger", "category": "market_sentiment", "title": "dragon tiger", '
                '"url": "", "summary": "net_amount=1000.0", '
                '"risk_tags": ["dragon_tiger", "dragon_tiger_positive"]}\n',
                encoding="utf-8",
            )

            dataset = load_research_dataset(features_path, universe_path, information_path=information_path)

        score = build_stock_scores(dataset)[(date(2026, 6, 3), "000001.SZ")]

        self.assertEqual(score.components["sentiment"].score, 5.0)
        self.assertNotIn("dragon_tiger_positive", score.missing_fields)

    def test_dragon_tiger_information_uses_latest_same_symbol_past_record(self) -> None:
        from fintech_quant.information import InformationCategory, InformationRecord
        from fintech_quant.research.dataset import FeatureRow, ResearchDataset
        from fintech_quant.research.scoring import build_stock_scores

        dataset = ResearchDataset(
            features=[
                FeatureRow(
                    symbol="000001.SZ",
                    trade_date=date(2026, 6, 3),
                    values={
                        "symbol": "000001.SZ",
                        "trade_date": date(2026, 6, 3),
                        "limit_up_streak": 0,
                    },
                )
            ],
            fundamentals={},
            capital_flow={},
            market_state={},
            information_records=[
                _dragon_tiger_record("000001", date(2026, 6, 1), "dragon_tiger_positive"),
                _dragon_tiger_record("000001", date(2026, 6, 2), "dragon_tiger_negative"),
                _dragon_tiger_record("000002", date(2026, 6, 3), "dragon_tiger_positive"),
                _dragon_tiger_record("000001", date(2026, 6, 4), "dragon_tiger_positive"),
            ],
            universe_symbols=("000001.SZ",),
        )

        score = build_stock_scores(dataset)[(date(2026, 6, 3), "000001.SZ")]

        self.assertEqual(score.components["sentiment"].score, 5.0)
        self.assertNotIn("dragon_tiger_positive", score.missing_fields)

def _dragon_tiger_record(symbol: str, published_at: date, tag: str):
    from fintech_quant.information import InformationCategory, InformationRecord

    return InformationRecord(
        symbol=symbol,
        sector=None,
        published_at=published_at,
        source="akshare_dragon_tiger",
        category=InformationCategory.MARKET_SENTIMENT,
        title="dragon tiger",
        url="",
        summary="net_amount=1000.0",
        risk_tags=("dragon_tiger", tag),
    )


if __name__ == "__main__":
    unittest.main()
