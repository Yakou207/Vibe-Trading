from __future__ import annotations

import unittest
from datetime import date


class ResearchRiskBuilderTest(unittest.TestCase):
    def test_build_risk_input_uses_portfolio_and_single_position_drawdown(self) -> None:
        from fintech_quant.research.risk_builder import PortfolioRiskState, PositionState, build_risk_input

        risk_input = build_risk_input(
            "000001.SZ",
            date(2026, 1, 2),
            8.0,
            PortfolioRiskState(
                equity=85000.0,
                rolling_peak=100000.0,
                positions={"000001.SZ": PositionState(shares=1000, cost_basis=10.0, market_value=8000.0)},
            ),
        )

        self.assertEqual(risk_input.portfolio_drawdown, 0.15)
        self.assertEqual(risk_input.single_position_drawdown, 0.2)
        self.assertEqual(risk_input.position_weight, round(8000.0 / 85000.0, 6))

    def test_build_risk_input_maps_fundamental_capital_market_and_information(self) -> None:
        from fintech_quant.information import InformationCategory, InformationRecord
        from fintech_quant.research.risk_builder import PortfolioRiskState, build_risk_input

        negative_record = InformationRecord(
            symbol="000001",
            sector=None,
            published_at=date(2026, 1, 1),
            source="fixture",
            category=InformationCategory.COMPANY_ANNOUNCEMENT,
            title="Negative announcement",
            url="https://example.test/st",
            summary="Negative fixture.",
            risk_tags=("negative_announcement",),
        )
        st_record = InformationRecord(
            symbol="000001",
            sector=None,
            published_at=date(2026, 1, 1),
            source="fixture",
            category=InformationCategory.COMPANY_ANNOUNCEMENT,
            title="ST warning",
            url="https://example.test/st",
            summary="ST fixture.",
            risk_tags=("st_warning",),
        )

        risk_input = build_risk_input(
            "000001.SZ",
            date(2026, 1, 2),
            10.0,
            PortfolioRiskState(equity=100000.0, rolling_peak=100000.0, positions={}),
            fundamentals={"st_warning": False, "goodwill_ratio": 0.35, "pledge_ratio": 0.6},
            capital_flow={"main_outflow_days": 4},
            market_state={"index_below_annual_ma": True, "broad_market_drop_gt_3pct_count": 16},
            information_records=[negative_record, st_record],
        )

        self.assertTrue(risk_input.st_warning)
        self.assertEqual(risk_input.negative_event_count, 1)
        self.assertEqual(risk_input.goodwill_ratio, 0.35)
        self.assertEqual(risk_input.pledge_ratio, 0.6)
        self.assertEqual(risk_input.main_outflow_days, 4)
        self.assertTrue(risk_input.index_below_annual_ma)
        self.assertEqual(risk_input.broad_market_drop_gt_3pct_count, 16)

    def test_build_risk_input_counts_sector_negative_information(self) -> None:
        from fintech_quant.information import InformationCategory, InformationRecord
        from fintech_quant.research.risk_builder import PortfolioRiskState, build_risk_input

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

        risk_input = build_risk_input(
            "000001.SZ",
            date(2026, 1, 2),
            10.0,
            PortfolioRiskState(equity=100000.0, rolling_peak=100000.0, positions={}),
            sector="新能源",
            information_records=[sector_record],
        )

        self.assertEqual(risk_input.negative_event_count, 1)

    def test_build_risk_input_maps_sector_st_warning(self) -> None:
        from fintech_quant.information import InformationCategory, InformationRecord
        from fintech_quant.research.risk_builder import PortfolioRiskState, build_risk_input

        sector_record = InformationRecord(
            symbol=None,
            sector="新能源",
            published_at=date(2026, 1, 1),
            source="fixture",
            category=InformationCategory.REGULATORY_POLICY,
            title="Sector ST pressure",
            url="https://example.test/policy",
            summary="Sector policy fixture.",
            risk_tags=("st_warning",),
        )

        risk_input = build_risk_input(
            "000001.SZ",
            date(2026, 1, 2),
            10.0,
            PortfolioRiskState(equity=100000.0, rolling_peak=100000.0, positions={}),
            sector="新能源",
            information_records=[sector_record],
        )

        self.assertTrue(risk_input.st_warning)


if __name__ == "__main__":
    unittest.main()
