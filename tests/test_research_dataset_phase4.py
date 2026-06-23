from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path


class Phase4ResearchDatasetTest(unittest.TestCase):
    def test_load_research_dataset_normalizes_sorts_and_filters_universe(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            features_path = root / "features.csv"
            universe_path.write_text("symbol,name,sector\n000001,Ping An,Bank\n", encoding="utf-8")
            _write_csv(
                features_path,
                [
                    _feature_row("600000.SH", "2026-01-01", 20.0),
                    _feature_row("000001", "2026-01-02", 11.0),
                    _feature_row("000001", "2026-01-01", 10.0),
                ],
            )

            dataset = load_research_dataset(features_path, universe_path)

        self.assertEqual(dataset.universe_symbols, ("000001.SZ",))
        self.assertEqual(
            [(row.trade_date.isoformat(), row.symbol) for row in dataset.features],
            [("2026-01-01", "000001.SZ"), ("2026-01-02", "000001.SZ")],
        )
        self.assertEqual(dataset.features[0].values["close"], 10.0)
        self.assertEqual(dataset.features[0].values["macd_positive"], True)

    def test_load_research_dataset_rejects_duplicate_feature_rows(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            features_path = root / "features.csv"
            universe_path.write_text("symbol\n000001\n", encoding="utf-8")
            _write_csv(
                features_path,
                [
                    _feature_row("000001", "2026-01-01", 10.0),
                    _feature_row("000001.SZ", "2026-01-01", 10.5),
                ],
            )

            with self.assertRaisesRegex(ValueError, "Duplicate feature row"):
                load_research_dataset(features_path, universe_path)

    def test_load_research_dataset_loads_optional_supplemental_files(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.csv"
            features_path = root / "features.csv"
            fundamentals_path = root / "fundamentals.csv"
            capital_flow_path = root / "capital_flow.csv"
            market_state_path = root / "market_state.csv"
            information_path = root / "information.jsonl"
            universe_path.write_text("symbol,name,sector\n000001,Ping An,Bank\n", encoding="utf-8")
            _write_csv(features_path, [_feature_row("000001", "2026-01-01", 10.0)])
            fundamentals_path.write_text(
                "symbol,pe,pb,roe,growth,goodwill_ratio,pledge_ratio,st_warning\n"
                "000001,18,1.5,0.16,0.12,0.35,0.6,true\n",
                encoding="utf-8",
            )
            capital_flow_path.write_text(
                "symbol,trade_date,main_net_inflow,main_outflow_days,margin_financing_positive\n"
                "000001,2026-01-02,-1000,4,false\n",
                encoding="utf-8",
            )
            market_state_path.write_text(
                "trade_date,index_below_annual_ma,broad_market_drop_gt_3pct_count\n"
                "2026-01-02,true,16\n",
                encoding="utf-8",
            )
            information_path.write_text(
                json.dumps(
                    {
                        "symbol": "000001",
                        "sector": "Bank",
                        "published_at": "2026-01-02",
                        "source": "fixture",
                        "category": "company_announcement",
                        "title": "Risk notice",
                        "url": "https://example.test/risk",
                        "summary": "Risk fixture.",
                        "risk_tags": ["negative_announcement"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            dataset = load_research_dataset(
                features_path,
                universe_path,
                fundamentals_path=fundamentals_path,
                capital_flow_path=capital_flow_path,
                market_state_path=market_state_path,
                information_path=information_path,
            )

        self.assertEqual(dataset.fundamentals[("000001.SZ", None)].values["pe"], 18.0)
        self.assertEqual(dataset.fundamentals[("000001.SZ", None)].values["st_warning"], True)
        self.assertEqual(dataset.capital_flow[("000001.SZ", date(2026, 1, 2))].values["main_outflow_days"], 4)
        self.assertEqual(dataset.market_state[date(2026, 1, 2)].values["index_below_annual_ma"], True)
        self.assertEqual(dataset.information_records[0].title, "Risk notice")
        self.assertEqual(dataset.information_records[0].normalized_symbol, "000001.SZ")


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = list(rows[0])
    lines = [",".join(fieldnames)]
    for row in rows:
        lines.append(",".join(str(row[field]) for field in fieldnames))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _feature_row(symbol: str, trade_date: str, close: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1000,
        "amount": close * 1000,
        "source": "fixture",
        "return_1d": 0.01,
        "ma20": close - 1,
        "ma60": close - 2,
        "ma250": close - 3,
        "close_above_ma20": "true",
        "close_above_ma60": "true",
        "close_above_ma250": "true",
        "rsi14": 55,
        "macd_line": 0.1,
        "macd_signal": 0.05,
        "macd_hist": 0.05,
        "macd_positive": "true",
        "volatility20": 0.02,
    }


if __name__ == "__main__":
    unittest.main()
