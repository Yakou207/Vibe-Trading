from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class RlDatasetTest(unittest.TestCase):
    def test_build_rl_state_samples_joins_scores_and_forward_returns(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset
        from fintech_quant.training import DEFAULT_RL_STATE_FIELDS, build_rl_state_samples

        with tempfile.TemporaryDirectory() as tmp:
            paths = _write_fixture_inputs(Path(tmp))
            dataset = load_research_dataset(
                paths["features"],
                paths["universe"],
                fundamentals_path=paths["fundamentals"],
                capital_flow_path=paths["capital_flow"],
            )

        samples = build_rl_state_samples(dataset)

        self.assertEqual(len(samples), 1)
        sample = samples[0]
        self.assertEqual(sample.symbol, "000001.SZ")
        self.assertEqual(sample.trade_date.isoformat(), "2026-01-01")
        self.assertEqual(sample.next_trade_date.isoformat(), "2026-01-02")
        self.assertEqual(sample.state_fields, DEFAULT_RL_STATE_FIELDS)
        self.assertEqual(len(sample.state_vector), len(DEFAULT_RL_STATE_FIELDS))
        self.assertAlmostEqual(sample.forward_return_1d, 0.1)
        self.assertEqual(sample.terminal, False)
        state = dict(zip(sample.state_fields, sample.state_vector, strict=True))
        self.assertEqual(state["pe"], 18.0)
        self.assertGreater(state["score_total"], 0.0)
        self.assertGreater(state["technical_score"], 0.0)

    def test_build_rl_state_samples_uses_information_capital_flow(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset
        from fintech_quant.training import build_rl_state_samples

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _write_fixture_inputs(root)
            information = root / "information.jsonl"
            information.write_text(
                '{"symbol": "000001", "sector": null, "published_at": "2026-01-01", '
                '"source": "akshare_fund_flow", "category": "stock_data", "title": "fund flow", '
                '"url": "", "summary": "main_net_inflow=1000.0", '
                '"risk_tags": ["selected_universe", "capital_flow", "main_inflow"]}\n',
                encoding="utf-8",
            )
            dataset = load_research_dataset(
                paths["features"],
                paths["universe"],
                fundamentals_path=paths["fundamentals"],
                information_path=information,
            )

        sample = build_rl_state_samples(dataset)[0]
        state = dict(zip(sample.state_fields, sample.state_vector, strict=True))

        self.assertEqual(state["main_net_inflow"], 1000.0)

    def test_build_rl_state_samples_includes_benchmark_forward_return(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset
        from fintech_quant.training import build_rl_state_samples

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _write_fixture_inputs(root)
            market_state = root / "market_state.csv"
            market_state.write_text(
                "trade_date,index_symbol,index_close,index_ma250,index_below_annual_ma\n"
                "2026-01-01,sh000001,100,100,false\n"
                "2026-01-02,sh000001,102,100,false\n",
                encoding="utf-8",
            )
            dataset = load_research_dataset(
                paths["features"],
                paths["universe"],
                fundamentals_path=paths["fundamentals"],
                capital_flow_path=paths["capital_flow"],
                market_state_path=market_state,
            )

        sample = build_rl_state_samples(dataset)[0]

        self.assertAlmostEqual(sample.forward_return_1d, 0.1)
        self.assertAlmostEqual(sample.benchmark_return_1d, 0.02)

    def test_build_rl_state_samples_uses_dragon_tiger_information(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset
        from fintech_quant.training import build_rl_state_samples

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _write_fixture_inputs(root)
            information = root / "information.jsonl"
            information.write_text(
                '{"symbol": "000001", "sector": null, "published_at": "2026-01-01", '
                '"source": "akshare_dragon_tiger", "category": "market_sentiment", "title": "dragon tiger", '
                '"url": "", "summary": "net_amount=1000.0", '
                '"risk_tags": ["dragon_tiger", "dragon_tiger_positive"]}\n',
                encoding="utf-8",
            )
            dataset = load_research_dataset(
                paths["features"],
                paths["universe"],
                fundamentals_path=paths["fundamentals"],
                capital_flow_path=paths["capital_flow"],
                information_path=information,
            )

        sample = build_rl_state_samples(dataset)[0]
        state = dict(zip(sample.state_fields, sample.state_vector, strict=True))

        self.assertEqual(state["dragon_tiger_positive"], 1.0)

    def test_write_rl_state_jsonl_serializes_stable_rows(self) -> None:
        from fintech_quant.research.dataset import load_research_dataset
        from fintech_quant.training import build_rl_state_samples, load_rl_state_jsonl, write_rl_state_jsonl

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _write_fixture_inputs(root)
            dataset = load_research_dataset(
                paths["features"],
                paths["universe"],
                fundamentals_path=paths["fundamentals"],
                capital_flow_path=paths["capital_flow"],
            )
            output_path = root / "rl_state.jsonl"
            write_rl_state_jsonl(output_path, build_rl_state_samples(dataset))

            rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
            loaded_samples = load_rl_state_jsonl(output_path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "000001.SZ")
        self.assertEqual(rows[0]["trade_date"], "2026-01-01")
        self.assertEqual(rows[0]["next_trade_date"], "2026-01-02")
        self.assertEqual(rows[0]["forward_return_1d"], 0.1)
        self.assertEqual(rows[0]["benchmark_return_1d"], 0.0)
        self.assertIsInstance(rows[0]["state_vector"], list)
        self.assertEqual(len(loaded_samples), 1)
        self.assertEqual(loaded_samples[0].symbol, "000001.SZ")
        self.assertEqual(loaded_samples[0].trade_date.isoformat(), "2026-01-01")
        self.assertEqual(loaded_samples[0].state_vector, tuple(rows[0]["state_vector"]))
        self.assertEqual(loaded_samples[0].benchmark_return_1d, 0.0)

    def test_group_rl_state_samples_by_symbol_marks_episode_terminals(self) -> None:
        from fintech_quant.training import RlStateSample, group_rl_state_samples_by_symbol

        samples = [
            RlStateSample("600000.SH", _date("2026-01-02"), _date("2026-01-03"), ("x",), (3.0,), 0.03),
            RlStateSample("000001.SZ", _date("2026-01-02"), _date("2026-01-03"), ("x",), (2.0,), 0.02),
            RlStateSample("000001.SZ", _date("2026-01-01"), _date("2026-01-02"), ("x",), (1.0,), 0.01),
        ]

        grouped = group_rl_state_samples_by_symbol(samples)

        self.assertEqual(tuple(grouped), ("000001.SZ", "600000.SH"))
        self.assertEqual(len(grouped["000001.SZ"]), 1)
        self.assertEqual(
            [sample.trade_date.isoformat() for sample in grouped["000001.SZ"][0]],
            ["2026-01-01", "2026-01-02"],
        )
        self.assertFalse(grouped["000001.SZ"][0][0].terminal)
        self.assertTrue(grouped["000001.SZ"][0][1].terminal)
        self.assertTrue(grouped["600000.SH"][0][0].terminal)

    def test_group_rl_state_samples_by_symbol_preserves_terminal_boundaries(self) -> None:
        from fintech_quant.training import RlStateSample, group_rl_state_samples_by_symbol

        samples = [
            RlStateSample("000001.SZ", _date("2026-01-01"), _date("2026-01-02"), ("x",), (1.0,), 0.01, terminal=True),
            RlStateSample("000001.SZ", _date("2026-01-02"), _date("2026-01-03"), ("x",), (2.0,), 0.02),
        ]

        grouped = group_rl_state_samples_by_symbol(samples)

        self.assertEqual(len(grouped["000001.SZ"]), 2)
        self.assertTrue(grouped["000001.SZ"][0][0].terminal)
        self.assertTrue(grouped["000001.SZ"][1][0].terminal)

    def test_group_rl_state_samples_by_symbol_splits_transition_gaps(self) -> None:
        from fintech_quant.training import RlStateSample, group_rl_state_samples_by_symbol

        samples = [
            RlStateSample("000001.SZ", _date("2026-01-01"), _date("2026-01-02"), ("x",), (1.0,), 0.01),
            RlStateSample("000001.SZ", _date("2026-01-03"), _date("2026-01-04"), ("x",), (2.0,), 0.02),
        ]

        grouped = group_rl_state_samples_by_symbol(samples)

        self.assertEqual(len(grouped["000001.SZ"]), 2)
        self.assertTrue(grouped["000001.SZ"][0][0].terminal)
        self.assertTrue(grouped["000001.SZ"][1][0].terminal)

    def test_group_rl_state_samples_by_symbol_rejects_state_field_changes_inside_episode(self) -> None:
        from fintech_quant.training import RlStateSample, group_rl_state_samples_by_symbol

        samples = [
            RlStateSample("000001.SZ", _date("2026-01-01"), _date("2026-01-02"), ("x",), (1.0,), 0.01),
            RlStateSample("000001.SZ", _date("2026-01-02"), _date("2026-01-03"), ("y",), (2.0,), 0.02),
        ]

        with self.assertRaisesRegex(ValueError, "state_fields"):
            group_rl_state_samples_by_symbol(samples)

    def test_load_rl_state_jsonl_rejects_state_field_vector_mismatch(self) -> None:
        from fintech_quant.training import load_rl_state_jsonl

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad_rl_state.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "symbol": "000001.SZ",
                        "trade_date": "2026-01-01",
                        "next_trade_date": "2026-01-02",
                        "state_fields": ["x", "y"],
                        "state_vector": [1.0],
                        "forward_return_1d": 0.01,
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "state_vector"):
                load_rl_state_jsonl(path)

    def test_build_rl_dataset_script_writes_jsonl_from_research_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _write_fixture_inputs(root)
            output_path = root / "rl_state.jsonl"

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_rl_dataset.py",
                    "--features",
                    str(paths["features"]),
                    "--universe",
                    str(paths["universe"]),
                    "--fundamentals",
                    str(paths["fundamentals"]),
                    "--capital-flow",
                    str(paths["capital_flow"]),
                    "--output",
                    str(output_path),
                ],
                cwd=Path(__file__).resolve().parents[1],
                check=True,
                capture_output=True,
                text=True,
            )

            rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]

        self.assertIn("samples=1", completed.stdout)
        self.assertEqual(rows[0]["symbol"], "000001.SZ")


def _write_fixture_inputs(root: Path) -> dict[str, Path]:
    universe = root / "universe.csv"
    features = root / "features.csv"
    fundamentals = root / "fundamentals.csv"
    capital_flow = root / "capital_flow.csv"
    universe.write_text("symbol,name,sector\n000001,Ping An,Bank\n", encoding="utf-8")
    features.write_text(
        "symbol,trade_date,open,high,low,close,volume,amount,source,return_1d,ma20,ma60,ma250,"
        "close_above_ma20,close_above_ma60,close_above_ma250,rsi14,macd_line,macd_signal,macd_hist,"
        "macd_positive,volatility20\n"
        "000001,2026-01-01,10,10,10,10,1000,10000,fixture,0.01,9,8,7,true,true,true,55,0.1,0.05,0.05,true,0.02\n"
        "000001,2026-01-02,11,11,11,11,1200,13200,fixture,0.10,9,8,7,true,true,true,60,0.2,0.08,0.12,true,0.03\n",
        encoding="utf-8",
    )
    fundamentals.write_text("symbol,pe,pb,roe,growth\n000001,18,1.5,0.16,0.12\n", encoding="utf-8")
    capital_flow.write_text(
        "symbol,trade_date,main_net_inflow,main_outflow_days,margin_financing_positive\n"
        "000001,2026-01-01,1000,0,true\n"
        "000001,2026-01-02,800,1,true\n",
        encoding="utf-8",
    )
    return {
        "universe": universe,
        "features": features,
        "fundamentals": fundamentals,
        "capital_flow": capital_flow,
    }


def _date(value: str) -> object:
    from datetime import date

    year, month, day = (int(part) for part in value.split("-"))
    return date(year, month, day)


if __name__ == "__main__":
    unittest.main()
