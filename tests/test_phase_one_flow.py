from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path


class PhaseOneFlowTest(unittest.TestCase):
    def test_fixture_backed_research_flow_reaches_baseline_decision(self) -> None:
        from fintech_quant.backtesting import EquityPoint, calculate_drawdown
        from fintech_quant.features import ScoreInput, score_stock
        from fintech_quant.information import InformationCategory, InformationRecord, InformationRepository
        from fintech_quant.risk import RiskAction, RiskInput, evaluate_risk
        from fintech_quant.strategies.scored_baseline import ScoredBaselineStrategy
        from fintech_quant.trading import TradeAction

        with tempfile.TemporaryDirectory() as tmp:
            repo = InformationRepository(Path(tmp) / "info.jsonl")
            repo.append(
                InformationRecord(
                    symbol="000001",
                    sector="bank",
                    published_at=date(2022, 1, 1),
                    source="exchange",
                    category=InformationCategory.FINANCIAL_REPORT,
                    title="Old report",
                    url="https://example.test/old-report",
                    summary="Old text record.",
                    risk_tags=(),
                )
            )
            repo.append(
                InformationRecord(
                    symbol="000001",
                    sector="bank",
                    published_at=date(2019, 1, 1),
                    source="local",
                    category=InformationCategory.STOCK_DATA,
                    title="Selected universe training row",
                    url="",
                    summary="Retained for RL.",
                    risk_tags=("selected_universe",),
                )
            )
            repo.append(
                InformationRecord(
                    symbol="000001",
                    sector="bank",
                    published_at=date(2026, 1, 2),
                    source="exchange",
                    category=InformationCategory.FINANCIAL_REPORT,
                    title="Recent report",
                    url="https://example.test/report",
                    summary="Revenue and ROE improved.",
                    risk_tags=(),
                )
            )
            all_records_before_prune = repo.query(symbol="000001")
            removed = repo.prune_text_records(today=date(2026, 6, 18))
            records_after_prune = repo.query(symbol="000001")
            normalized_records = repo.query(symbol="000001.SZ")

            score = score_stock(
                ScoreInput(
                    symbol="000001",
                    pe=18,
                    pb=1.5,
                    roe=0.16,
                    growth=0.12,
                    close_above_ma20=True,
                    close_above_ma60=True,
                    rsi=55,
                    macd_positive=True,
                    volume_confirmed=True,
                    main_net_inflow=1,
                    main_outflow_days=0,
                    margin_financing_positive=True,
                    limit_up_streak=1,
                    dragon_tiger_positive=True,
                    negative_event_count=len(
                        [
                            record
                            for record in repo.query(symbol="000001")
                            if "negative_announcement" in record.risk_tags
                        ]
                    ),
                )
            )
            risk = evaluate_risk(RiskInput(portfolio_drawdown=0.02))
            drawdown = calculate_drawdown(
                [
                    EquityPoint(date(2026, 1, 1), 100.0),
                    EquityPoint(date(2026, 1, 2), 108.0),
                    EquityPoint(date(2026, 1, 3), 106.0),
                ]
            )
            decision = ScoredBaselineStrategy().decide({"score": score, "risk_action": risk.action})

            self.assertEqual(len(all_records_before_prune), 3)
            self.assertEqual({record.normalized_symbol for record in all_records_before_prune}, {"000001.SZ"})
            self.assertEqual(removed, 1)
            self.assertEqual([record.title for record in records_after_prune], ["Selected universe training row", "Recent report"])
            self.assertEqual([record.title for record in normalized_records], ["Selected universe training row", "Recent report"])
            self.assertEqual(risk.action, RiskAction.NONE)
            self.assertLess(drawdown.max_drawdown, 0.15)
            self.assertEqual(decision.action, TradeAction.BUY)


if __name__ == "__main__":
    unittest.main()
