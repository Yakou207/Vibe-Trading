from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


class PaperTradingLoopTest(unittest.TestCase):
    def test_paper_account_persists_dividend_lot_and_withholds_tax_on_sale(self) -> None:
        from fintech_quant.backtesting import (
            CorporateAction,
            IndividualAShareDividendTaxPolicy,
        )
        from fintech_quant.execution.paper_account import (
            PaperAccount,
            load_paper_account,
            run_paper_trading_day,
            write_paper_account,
        )

        policy = IndividualAShareDividendTaxPolicy()
        bought = run_paper_trading_day(
            PaperAccount(cash=10000.0),
            targets={"000001.SZ": 1.0},
            bars={"000001.SZ": _bar("000001.SZ", 10.0)},
            as_of=date(2026, 1, 1),
            commission_rate=0.0,
            dividend_tax_policy=policy,
        )
        dividend = run_paper_trading_day(
            bought.account,
            targets={"000001.SZ": 0.9},
            bars={"000001.SZ": _bar("000001.SZ", 10.0)},
            as_of=date(2026, 1, 10),
            commission_rate=0.0,
            corporate_actions=(
                CorporateAction(
                    symbol="000001.SZ",
                    ex_date=date(2026, 1, 10),
                    cash_dividend_per_share=1.0,
                    source="fixture",
                ),
            ),
            dividend_tax_policy=policy,
        )

        with tempfile.TemporaryDirectory() as tmp:
            account_path = Path(tmp) / "account.json"
            write_paper_account(account_path, dividend.account)
            restored = load_paper_account(account_path, initial_cash=0.0)

        sold = run_paper_trading_day(
            restored,
            targets={"000001.SZ": 0.0},
            bars={"000001.SZ": _bar("000001.SZ", 10.0)},
            as_of=date(2026, 1, 20),
            commission_rate=0.0,
            dividend_tax_policy=policy,
        )

        self.assertEqual(dividend.account.cash, 1000.0)
        self.assertEqual(
            restored.dividend_tax_lots["000001.SZ"][0].pending_dividend,
            1000.0,
        )
        self.assertEqual(sold.trades[0]["dividend_tax"], 200.0)
        self.assertEqual(sold.account.cash, 10800.0)

    def test_paper_account_applies_persisted_reduced_regime_and_tracks_shadow_book(self) -> None:
        from fintech_quant.backtesting import DrawdownControlPolicy
        from fintech_quant.backtesting.drawdown_control import (
            DrawdownControlState,
            DrawdownRegime,
        )
        from fintech_quant.execution.paper_account import PaperAccount, run_paper_trading_day

        account = PaperAccount(
            cash=10000.0,
            shadow_cash=10000.0,
            drawdown_control_state=DrawdownControlState(
                regime=DrawdownRegime.REDUCED,
                actual_peak=10000.0,
                shadow_peak=10000.0,
                last_transition_date=date(2026, 1, 1),
            ),
        )

        result = run_paper_trading_day(
            account,
            targets={"000001.SZ": 1.0},
            bars={"000001.SZ": {"close": 10.0}},
            as_of=date(2026, 1, 2),
            commission_rate=0.0,
            drawdown_policy=DrawdownControlPolicy(),
        )

        self.assertEqual(result.trades[0]["shares"], 500)
        self.assertEqual(result.account.positions["000001.SZ"].shares, 500)
        self.assertEqual(result.account.shadow_positions["000001.SZ"].shares, 1000)
        self.assertEqual(result.nav["applied_drawdown_regime"], "reduced")
        self.assertEqual(result.account.drawdown_control_state.regime, DrawdownRegime.NORMAL)

    def test_paper_trading_day_buys_target_weight_and_persists_nav(self) -> None:
        from fintech_quant.execution.paper_account import PaperAccount, run_paper_trading_day

        account = PaperAccount(cash=100000.0)

        result = run_paper_trading_day(
            account,
            targets={"000001.SZ": 0.10},
            bars={"000001.SZ": _bar("000001.SZ", 10.0)},
            as_of=date.fromisoformat("2026-01-02"),
            commission_rate=0.0,
        )

        self.assertEqual(result.account.positions["000001.SZ"].shares, 1000)
        self.assertEqual(result.account.cash, 90000.0)
        self.assertEqual(result.nav["equity"], 100000.0)
        self.assertEqual(result.trades[0]["action"], "buy")

    def test_paper_trading_executes_pending_target_at_session_open_and_marks_close(self) -> None:
        from fintech_quant.execution.paper_account import PaperAccount, run_paper_trading_day

        result = run_paper_trading_day(
            PaperAccount(cash=100000.0),
            targets={"000001.SZ": 0.10},
            bars={"000001.SZ": _bar("000001.SZ", 12.0, open=10.0)},
            as_of=date(2026, 1, 5),
            commission_rate=0.0,
        )

        self.assertEqual(result.trades[0]["price"], 10.0)
        self.assertEqual(result.trades[0]["shares"], 1000)
        self.assertEqual(result.nav["positions_value"], 12000.0)
        self.assertEqual(result.nav["equity"], 102000.0)

    def test_paper_trading_uses_minimum_commission_and_sell_stamp_duty(self) -> None:
        from fintech_quant.backtesting import AShareCostModel
        from fintech_quant.execution.paper_account import PaperAccount, run_paper_trading_day

        cost_model = AShareCostModel(
            commission_rate=0.0003,
            minimum_commission=5.0,
            include_stamp_duty=True,
        )
        bought = run_paper_trading_day(
            PaperAccount(cash=10000.0),
            targets={"000001.SZ": 0.10},
            bars={"000001.SZ": _bar("000001.SZ", 10.0)},
            as_of=date(2026, 1, 2),
            cost_model=cost_model,
        )
        sold = run_paper_trading_day(
            bought.account,
            targets={"000001.SZ": 0.0},
            bars={"000001.SZ": _bar("000001.SZ", 10.0)},
            as_of=date(2026, 1, 5),
            cost_model=cost_model,
        )

        self.assertEqual(bought.trades[0]["commission"], 5.0)
        self.assertEqual(bought.trades[0]["stamp_duty"], 0.0)
        self.assertEqual(sold.trades[0]["commission"], 5.0)
        self.assertEqual(sold.trades[0]["stamp_duty"], 0.5)
        self.assertEqual(sold.trades[0]["total_cost"], 5.5)
        self.assertEqual(sold.account.cash, 9989.5)

    def test_paper_trading_day_enforces_t_plus_one_and_limit_constraints(self) -> None:
        from fintech_quant.execution.paper_account import (
            PaperAccount,
            PaperPosition,
            run_paper_trading_day,
        )

        account = PaperAccount(
            cash=90000.0,
            positions={
                "000001.SZ": PaperPosition(
                    shares=1000,
                    cost_basis=10.0,
                    last_buy_date=date.fromisoformat("2026-01-02"),
                )
            },
        )

        same_day = run_paper_trading_day(
            account,
            targets={"000001.SZ": 0.0},
            bars={"000001.SZ": _bar("000001.SZ", 9.0)},
            as_of=date.fromisoformat("2026-01-02"),
            commission_rate=0.0,
        )
        next_day_limit_down = run_paper_trading_day(
            account,
            targets={"000001.SZ": 0.0},
            bars={"000001.SZ": _bar("000001.SZ", 9.0, limit_down=True)},
            as_of=date.fromisoformat("2026-01-03"),
            commission_rate=0.0,
        )

        self.assertEqual(same_day.trades, [])
        self.assertEqual(same_day.blocked_orders[0]["reason"], "t_plus_one")
        self.assertEqual(next_day_limit_down.trades, [])
        self.assertEqual(next_day_limit_down.blocked_orders[0]["reason"], "limit_down")

    def test_paper_trading_day_blocks_limit_up_buys(self) -> None:
        from fintech_quant.execution.paper_account import PaperAccount, run_paper_trading_day

        result = run_paper_trading_day(
            PaperAccount(cash=100000.0),
            targets={"000001.SZ": 0.10},
            bars={"000001.SZ": _bar("000001.SZ", 10.0, limit_up=True)},
            as_of=date.fromisoformat("2026-01-02"),
        )

        self.assertEqual(result.trades, [])
        self.assertEqual(result.blocked_orders[0]["reason"], "limit_up")

    def test_paper_account_rejects_duplicate_or_out_of_order_processing_date(self) -> None:
        from fintech_quant.execution.paper_account import PaperAccount, run_paper_trading_day

        first = run_paper_trading_day(
            PaperAccount(cash=100000.0),
            targets={},
            bars={},
            as_of=date(2026, 1, 5),
        )

        with self.assertRaisesRegex(ValueError, "after last processed date"):
            run_paper_trading_day(
                first.account,
                targets={},
                bars={},
                as_of=date(2026, 1, 5),
            )

    def test_paper_trading_script_writes_account_and_daily_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_path = root / "account.json"
            targets_path = root / "targets.csv"
            prices_path = root / "prices.csv"
            report_path = root / "report.json"
            targets_path.write_text("symbol,target_weight\n000001.SZ,0.10\n", encoding="utf-8")
            prices_path.write_text(
                "symbol,trade_date,close,limit_up,limit_down,is_suspended\n"
                "000001.SZ,2026-01-02,10,false,false,false\n",
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_paper_trading_loop.py",
                    "--account",
                    str(account_path),
                    "--targets",
                    str(targets_path),
                    "--prices",
                    str(prices_path),
                    "--as-of",
                    "2026-01-02",
                    "--report",
                    str(report_path),
                    "--initial-cash",
                    "100000",
                    "--commission-rate",
                    "0",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )
            account = json.loads(account_path.read_text(encoding="utf-8"))
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        self.assertIn("trade_count=1", completed.stdout)
        self.assertEqual(account["positions"]["000001.SZ"]["shares"], 1000)
        self.assertEqual(
            account["dividend_tax_lots"]["000001.SZ"][0]["shares"],
            1000,
        )
        self.assertEqual(report["nav"]["equity"], 100000.0)


def _bar(symbol: str, close: float, **overrides: object) -> dict[str, object]:
    row = {
        "symbol": symbol,
        "close": close,
        "is_suspended": False,
        "limit_up": False,
        "limit_down": False,
    }
    row.update(overrides)
    return row


if __name__ == "__main__":
    unittest.main()
