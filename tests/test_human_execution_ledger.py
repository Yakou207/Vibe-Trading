from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fintech_quant.execution.human_ledger import (
    LEDGER_FIELDS,
    LedgerError,
    append_entry,
    compare_to_paper,
    load_ledger,
    validate_entry,
)

BRIEF = {
    "signal_date": "2026-07-21",
    "targets": [
        {
            "symbol": "600001.SH",
            "category": "target",
            "previous_close": 10.0,
            "limit_up": 11.0,
            "limit_down": 9.0,
            "suggested": {"shares": 700},
        },
        {
            "symbol": "600002.SH",
            "category": "target",
            "previous_close": 20.0,
            "limit_up": 22.0,
            "limit_down": 18.0,
            "suggested": {"shares": 300},
        },
    ],
    "near_miss": [
        {
            "symbol": "600003.SH",
            "category": "near_miss",
            "previous_close": 5.0,
            "limit_up": 5.5,
            "limit_down": 4.5,
        }
    ],
    "paper_exits": [],
}


def _buy(**overrides: object) -> dict[str, object]:
    row = {
        "trade_date": "2026-07-22",
        "signal_date": "2026-07-21",
        "symbol": "600001",
        "action": "buy",
        "shares": "700",
        "fill_price": "10.10",
        "fees": "5",
    }
    row.update(overrides)
    return row


class LedgerValidationTest(unittest.TestCase):
    def test_valid_buy_is_normalized(self) -> None:
        row = validate_entry(_buy(), BRIEF)
        self.assertEqual(row["symbol"], "600001.SH")
        self.assertEqual(row["shares"], 700)
        self.assertEqual(row["fill_price"], 10.1)
        self.assertEqual(row["fees"], 5.0)

    def test_rejects_invalid_rows(self) -> None:
        cases = {
            "odd lot buy": _buy(shares="150"),
            "zero shares": _buy(shares="0"),
            "fractional shares": _buy(shares="100.5"),
            "missing price": _buy(fill_price=""),
            "negative fees": _buy(fees="-1"),
            "same-day trade": _buy(trade_date="2026-07-21"),
            "bad date": _buy(trade_date="22/07/2026"),
            "bad action": _buy(action="short"),
            "bad symbol": _buy(symbol="ABC"),
            "buy with skip reason": _buy(skip_reason="x"),
            "star below 200": _buy(symbol="688111", shares="100"),
            "skip without reason": _buy(action="skip", shares="", fill_price="", fees=""),
            "skip with fill": _buy(action="skip", skip_reason="gap up"),
        }
        for name, row in cases.items():
            with self.subTest(name), self.assertRaises(LedgerError):
                validate_entry(row)

    def test_brief_checks_limit_band_and_skip_target(self) -> None:
        with self.assertRaises(LedgerError):
            validate_entry(_buy(fill_price="11.01"), BRIEF)
        with self.assertRaises(LedgerError):
            validate_entry(_buy(fill_price="8.99"), BRIEF)
        self.assertEqual(validate_entry(_buy(fill_price="11.00"), BRIEF)["fill_price"], 11.0)
        skip = _buy(symbol="600003", action="skip", shares="", fill_price="", fees="")
        skip["skip_reason"] = "not a target"
        with self.assertRaises(LedgerError):
            validate_entry(skip, BRIEF)
        # Off-brief trades are allowed; the comparison report lists them.
        self.assertEqual(validate_entry(_buy(symbol="600999"), BRIEF)["symbol"], "600999.SH")

    def test_append_only_keeps_existing_rows_and_rejects_bad_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.csv"
            append_entry(path, _buy(), BRIEF)
            first = path.read_text(encoding="utf-8")
            with self.assertRaises(LedgerError):
                append_entry(path, _buy(shares="150"), BRIEF)
            self.assertEqual(path.read_text(encoding="utf-8"), first)
            append_entry(path, _buy(symbol="600002", shares="300", fill_price="19.9"), BRIEF)
            text = path.read_text(encoding="utf-8")
            rows = load_ledger(path)
        self.assertTrue(text.startswith(first))
        self.assertEqual(text.splitlines()[0], ",".join(LEDGER_FIELDS))
        self.assertEqual([r["symbol"] for r in rows], ["600001.SH", "600002.SH"])

    def test_load_rejects_wrong_header_and_bad_rows_with_line_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.csv"
            path.write_text("symbol,action\n600001.SH,buy\n", encoding="utf-8")
            with self.assertRaises(LedgerError):
                load_ledger(path)
            path.write_text(
                ",".join(LEDGER_FIELDS) + "\n2026-07-22,2026-07-21,600001.SH,buy,150,10,,,\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(LedgerError, ":2:"):
                load_ledger(path)


class CompareToPaperTest(unittest.TestCase):
    def test_shortfall_and_skip_rate(self) -> None:
        ledger = [
            validate_entry(_buy(shares="400", fill_price="10.10", fees="5")),
            validate_entry(_buy(shares="300", fill_price="10.20", fees="5")),
            validate_entry(
                _buy(symbol="600002", action="skip", shares="", fill_price="", fees="",
                     skip_reason="gapped up 6%")
            ),
            validate_entry(_buy(symbol="600999", shares="100", fill_price="3.0", fees="5")),
            validate_entry(_buy(signal_date="2026-07-16", trade_date="2026-07-17")),
        ]
        paper = [{"symbol": "600001.SH", "action": "buy", "price": 10.005, "shares": 700,
                  "total_cost": 5.0}]
        report = compare_to_paper(ledger, BRIEF, paper)
        orders = {o["symbol"]: o for o in report["orders"]}
        human = orders["600001.SH"]["human"]
        # VWAP (400*10.10 + 300*10.20) / 700; shortfall = 7100 - 7000 + 10 fees.
        self.assertEqual(human["shares"], 700)
        self.assertAlmostEqual(human["vwap"], 10.142857, places=6)
        self.assertEqual(human["shortfall_cny"], 110.0)
        self.assertEqual(human["shortfall_bps"], 157.14)
        self.assertEqual(orders["600001.SH"]["paper"]["shortfall_cny"], 8.5)
        self.assertAlmostEqual(orders["600001.SH"]["human_vs_paper_bps"], 137.79, places=2)
        self.assertEqual(orders["600002.SH"]["status"], "skipped")
        self.assertEqual(orders["600002.SH"]["skip_reasons"], ["gapped up 6%"])
        summary = report["summary"]
        self.assertEqual(summary["planned_orders"], 2)
        self.assertEqual(summary["skip_rate"], 0.5)
        self.assertEqual(summary["unrecorded"], 0)
        self.assertEqual(summary["off_brief_trades"], 1)
        self.assertFalse(report["counts_toward_paper_evidence"])

    def test_missing_paper_execution_and_unrecorded_targets(self) -> None:
        report = compare_to_paper([], BRIEF, None)
        self.assertFalse(report["paper_execution_available"])
        self.assertEqual(report["summary"]["unrecorded"], 2)
        self.assertEqual(report["summary"]["unrecorded_rate"], 1.0)
        self.assertIsNone(report["summary"]["paper_shortfall_cny"])


if __name__ == "__main__":
    unittest.main()
