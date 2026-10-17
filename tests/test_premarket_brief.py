from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from fintech_quant.reports.premarket_brief import (
    evaluate_auction,
    limit_prices,
    price_limit_rate,
    suggested_lot_quantity,
)

WORKTREE = Path(__file__).resolve().parents[1]
POLICY = {
    "buy_threshold": 70.0,
    "minimum_score_confidence": 0.8,
    "maximum_position_weight": 0.08,
    "commission_rate": 0.0003,
    "minimum_commission": 5.0,
    "slippage_rate": 0.0005,
}


class LotSizingTest(unittest.TestCase):
    def test_floors_to_whole_board_lots(self) -> None:
        result = suggested_lot_quantity(100_000, 0.08, 31.37, "002142.SZ")
        self.assertEqual(result["shares"], 200)
        self.assertEqual(result["notional"], 6274.0)
        self.assertEqual(result["estimated_commission"], 5.0)
        self.assertIsNone(result["reason"])

    def test_commission_removes_a_lot_that_would_overspend(self) -> None:
        # 8 lots at 10.00 cost exactly the 8,000 allocation; the 5 CNY minimum
        # commission pushes it over, so only 7 lots fit.
        result = suggested_lot_quantity(100_000, 0.08, 10.0, "600000.SH")
        self.assertEqual(result["shares"], 700)

    def test_allocation_below_one_lot_suggests_zero(self) -> None:
        result = suggested_lot_quantity(100_000, 0.08, 122.09, "300866.SZ")
        self.assertEqual(result["shares"], 0)
        self.assertEqual(result["reason"], "allocation_below_one_lot")

    def test_star_market_requires_at_least_200_shares(self) -> None:
        result = suggested_lot_quantity(100_000, 0.08, 50.0, "688111.SH")
        self.assertEqual(result["shares"], 0)
        self.assertEqual(result["reason"], "star_minimum_200_shares")
        self.assertEqual(suggested_lot_quantity(100_000, 0.08, 30.0, "688111.SH")["shares"], 200)

    def test_rejects_invalid_inputs(self) -> None:
        with self.assertRaises(ValueError):
            suggested_lot_quantity(0, 0.08, 10.0, "600000.SH")
        with self.assertRaises(ValueError):
            suggested_lot_quantity(100_000, 1.5, 10.0, "600000.SH")


class LimitPriceTest(unittest.TestCase):
    def test_board_specific_rates(self) -> None:
        day = date(2026, 7, 21)
        self.assertEqual(price_limit_rate("600000.SH", "浦发银行", day), 0.10)
        self.assertEqual(price_limit_rate("000001.SZ", "平安银行", day), 0.10)
        self.assertEqual(price_limit_rate("300866.SZ", "安克创新", day), 0.20)
        self.assertEqual(price_limit_rate("301269.SZ", "华大九天", day), 0.20)
        self.assertEqual(price_limit_rate("688111.SH", "金山办公", day), 0.20)
        self.assertEqual(price_limit_rate("830799.BJ", "艾融软件", day), 0.30)

    def test_main_board_st_rate_follows_2025_rule_change(self) -> None:
        self.assertEqual(price_limit_rate("600001.SH", "*ST样例", date(2025, 7, 4)), 0.05)
        self.assertEqual(price_limit_rate("600001.SH", "*ST样例", date(2025, 7, 7)), 0.10)
        self.assertEqual(price_limit_rate("300001.SZ", "ST样例", date(2024, 1, 2)), 0.20)

    def test_limit_prices_round_half_up_to_tick(self) -> None:
        self.assertEqual(limit_prices(10.05, 0.10), (11.06, 9.05))
        self.assertEqual(limit_prices(37.75, 0.20), (45.3, 30.2))
        self.assertEqual(limit_prices(5.22, 0.10), (5.74, 4.7))
        self.assertEqual(limit_prices(3.33, 0.05), (3.5, 3.16))

    def test_rejects_non_positive_close(self) -> None:
        with self.assertRaises(ValueError):
            limit_prices(0.0, 0.10)


class AuctionCheckTest(unittest.TestCase):
    def test_flags_limit_up_near_limit_and_gap_down(self) -> None:
        brief = {
            "signal_date": "2026-07-21",
            "capital": 100_000.0,
            "policy": POLICY,
            "targets": [
                _item("600001.SH", "target", 10.0),
                _item("600002.SH", "target", 10.0),
                _item("600003.SH", "target", 10.0),
                _item("600004.SH", "target", 10.0),
            ],
            "near_miss": [_item("600005.SH", "near_miss", 10.0)],
        }
        quotes = [
            {"symbol": "600001.SH", "price": "11.00"},
            {"symbol": "600002.SH", "price": "10.95"},
            {"symbol": "600003.SH", "price": "9.40"},
            {"symbol": "600005.SH", "price": "10.10"},
        ]
        checks = {c["symbol"]: c for c in evaluate_auction(brief, quotes)["checks"]}
        self.assertEqual(checks["600001.SH"]["flags"], ["at_limit_up_cannot_buy"])
        self.assertEqual(checks["600002.SH"]["flags"], ["near_limit_up"])
        self.assertEqual(checks["600003.SH"]["flags"], ["large_gap_down"])
        self.assertEqual(checks["600003.SH"]["suggested_at_auction"]["shares"], 800)
        self.assertEqual(checks["600004.SH"]["flags"], ["no_auction_quote"])
        self.assertEqual(checks["600005.SH"]["flags"], [])
        self.assertNotIn("suggested_at_auction", checks["600005.SH"])


class EvidenceUntouchedTest(unittest.TestCase):
    def test_brief_auction_and_ledger_never_modify_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cycle_root = root / "cycles"
            paper_root = root / "data" / "paper"
            build_fixture(cycle_root, paper_root)
            before = _snapshot(cycle_root, paper_root)
            common = ["--cycle-root", str(cycle_root), "--protect", str(paper_root)]
            brief_root = root / "premarket"
            ledger = root / "human" / "ledger.csv"

            self.assertEqual(
                _run(
                    "build_premarket_brief.py",
                    *common,
                    "--cycle-dir",
                    str(cycle_root / "2026-07-21"),
                    "--output-root",
                    str(brief_root),
                ),
                0,
            )
            quotes = root / "quotes.csv"
            quotes.write_text(
                "symbol,name,price,change_pct,change_amount,volume,amount,turnover_rate,"
                "pe_dynamic,pb,source\n600001.SH,甲,11.00,,,,,,,,json\n",
                encoding="utf-8",
            )
            self.assertEqual(
                _run(
                    "build_premarket_brief.py",
                    *common,
                    "--cycle-dir",
                    str(cycle_root / "2026-07-21"),
                    "--output-root",
                    str(brief_root),
                    "--auction",
                    "--quotes",
                    str(quotes),
                ),
                0,
            )
            ledger_args = [
                "--ledger",
                str(ledger),
                "--brief-root",
                str(brief_root),
                *common,
            ]
            self.assertEqual(
                _run(
                    "human_execution_ledger.py",
                    *ledger_args,
                    "add",
                    "--trade-date",
                    "2026-07-22",
                    "--signal-date",
                    "2026-07-21",
                    "--symbol",
                    "600002",
                    "--action",
                    "buy",
                    "--shares",
                    "700",
                    "--fill-price",
                    "10.05",
                    "--fees",
                    "5",
                ),
                0,
            )
            self.assertEqual(
                _run(
                    "human_execution_ledger.py",
                    *ledger_args,
                    "add",
                    "--trade-date",
                    "2026-07-22",
                    "--signal-date",
                    "2026-07-21",
                    "--symbol",
                    "600001.SH",
                    "--action",
                    "skip",
                    "--skip-reason",
                    "auction at limit-up",
                ),
                0,
            )
            self.assertEqual(
                _run(
                    "human_execution_ledger.py",
                    *ledger_args,
                    "report",
                    "--signal-date",
                    "2026-07-21",
                ),
                0,
            )
            # Writing into the evidence tree must be refused.
            self.assertNotEqual(
                _run(
                    "build_premarket_brief.py",
                    *common,
                    "--output-root",
                    str(cycle_root),
                ),
                0,
            )
            self.assertNotEqual(
                _run(
                    "human_execution_ledger.py",
                    "--ledger",
                    str(paper_root / "ledger.csv"),
                    *common,
                    "report",
                    "--signal-date",
                    "2026-07-21",
                ),
                0,
            )
            after = _snapshot(cycle_root, paper_root)

            brief = json.loads((brief_root / "2026-07-21" / "brief.json").read_text("utf-8"))
            report = json.loads(
                (brief_root / "2026-07-21" / "human_execution_report.json").read_text("utf-8")
            )
            self.assertTrue((brief_root / "2026-07-21" / "brief.html").exists())
            self.assertTrue((brief_root / "2026-07-21" / "brief_auction.html").exists())

        self.assertEqual(before, after)
        self.assertFalse(brief["counts_toward_paper_evidence"])
        self.assertEqual([t["symbol"] for t in brief["targets"]], ["600001.SH", "600002.SH"])
        self.assertEqual([t["symbol"] for t in brief["near_miss"]], ["600003.SH"])
        self.assertEqual(brief["targets"][1]["limit_up"], 11.0)
        self.assertEqual(report["summary"]["filled"], 1)
        self.assertEqual(report["summary"]["skipped"], 1)
        self.assertEqual(report["summary"]["skip_rate"], 0.5)
        orders = {o["symbol"]: o for o in report["orders"]}
        # Human paid 10.05 vs paper 10.005: 45 bps worse than the paper fill.
        self.assertAlmostEqual(orders["600002.SH"]["human_vs_paper_bps"], 44.98, places=2)

    def test_evidence_code_does_not_import_human_side_modules(self) -> None:
        evidence_sources = [
            WORKTREE / "src/fintech_quant/execution/paper_account.py",
            WORKTREE / "src/fintech_quant/execution/paper_evidence.py",
            WORKTREE / "src/fintech_quant/reports/paper_validation.py",
            WORKTREE / "scripts/run_csi300_post_close.py",
            WORKTREE / "scripts/run_daily_paper_trading.py",
            WORKTREE / "scripts/audit_csi300_paper_validation.py",
        ]
        for path in evidence_sources:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("human_ledger", text, msg=str(path))
            self.assertNotIn("premarket_brief", text, msg=str(path))


def build_fixture(cycle_root: Path, paper_root: Path) -> None:
    """A minimal V2 signal cycle (2026-07-21) and the cycle that executes it (2026-07-22)."""
    paper_root.mkdir(parents=True)
    (paper_root / "account.json").write_text('{"cash": 100000.0}\n', encoding="utf-8")
    (paper_root / "pipeline_state.json").write_text('{"schema_version": 1}\n', encoding="utf-8")
    prices = cycle_root.parent / "prices" / "daily.csv"
    prices.parent.mkdir(parents=True)
    prices.write_text(
        "symbol,trade_date,open,high,low,close,volume,amount,source\n"
        "600001.SH,2026-07-20,9.0,9.0,9.0,9.0,1,1,fixture\n"
        "600001.SH,2026-07-21,9.5,10.1,9.4,10.0,1,1,fixture\n"
        "600002.SH,2026-07-21,9.9,10.0,9.8,10.0,1,1,fixture\n"
        "600003.SH,2026-07-21,20.0,20.0,20.0,20.0,1,1,fixture\n"
        "600002.SH,2026-07-22,10.0,10.2,9.9,10.1,1,1,fixture\n",
        encoding="utf-8",
    )
    signal = cycle_root / "2026-07-21"
    signal.mkdir(parents=True)
    _write_csv(
        signal / "current_universe.csv",
        ["symbol", "name"],
        [["600001.SH", "甲"], ["600002.SH", "乙"], ["600003.SH", "丙"], ["600004.SH", "丁"]],
    )
    _write_csv(
        signal / "targets.csv",
        ["symbol", "raw_target_weight", "target_weight", "score", "score_confidence"],
        [["600001.SH", 0.08, 0.08, 75, 0.8125], ["600002.SH", 0.08, 0.08, 72, 0.8125]],
    )
    scores = [
        _score("600001.SH", 75.0),
        _score("600002.SH", 72.0),
        _score("600003.SH", 66.0),
        _score("600004.SH", 50.0),
    ]
    _write_json(
        signal / "decision_report.json",
        {"as_of": "2026-07-21", "scores": scores, "risk_warnings": [], "risk_summary": {}},
    )
    _write_json(
        signal / "paper_report.json",
        {
            "account": {
                "pending_signal_date": "2026-07-21",
                "pending_targets": {"600001.SH": 0.08, "600002.SH": 0.08},
                "positions": {},
            },
            "nav": {"executed_signal_date": "2026-07-16"},
            "trades": [],
        },
    )
    _write_manifest(signal, "2026-07-21", prices)

    execution = cycle_root / "2026-07-22"
    execution.mkdir()
    (execution / "current_universe.csv").write_bytes((signal / "current_universe.csv").read_bytes())
    _write_csv(execution / "targets.csv", ["symbol"], [])
    _write_json(
        execution / "paper_report.json",
        {
            "account": {
                "pending_signal_date": "2026-07-22",
                "pending_targets": {},
                "positions": {},
            },
            "nav": {"executed_signal_date": "2026-07-21"},
            "trades": [
                {
                    "symbol": "600002.SH",
                    "action": "buy",
                    "price": 10.005,
                    "shares": 700,
                    "total_cost": 5.0,
                }
            ],
        },
    )
    _write_manifest(execution, "2026-07-22", prices)


def _write_manifest(cycle: Path, as_of: str, prices: Path) -> None:
    _write_json(
        cycle / "cycle_manifest.json",
        {
            "schema_version": 2,
            "kind": "paper_trading_cycle",
            "as_of": as_of,
            "policy": POLICY,
            "artifacts": {
                "targets": _ref(cycle / "targets.csv"),
                "paper_report": _ref(cycle / "paper_report.json"),
            },
            "inputs": {
                "execution_prices": _ref(prices),
                "current_universe": _ref(cycle / "current_universe.csv"),
            },
        },
    )


def _item(symbol: str, category: str, close: float) -> dict[str, object]:
    up, down = limit_prices(close, 0.10)
    return {
        "symbol": symbol,
        "category": category,
        "previous_close": close,
        "limit_up": up,
        "limit_down": down,
        "target_weight": 0.08,
    }


def _score(symbol: str, total: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "total": total,
        "confidence": 0.8125,
        "missing_fields": [],
        "components": {"technical": {"score": 10.0, "max_score": 25.0, "reasons": ["fixture"]}},
    }


def _ref(path: Path) -> dict[str, object]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _snapshot(*roots: Path) -> dict[str, tuple[str, int]]:
    return {
        str(path): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
        for root in roots
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _run(script: str, *args: str) -> int:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, f"scripts/{script}", *args],
        cwd=WORKTREE,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    unittest.main()
