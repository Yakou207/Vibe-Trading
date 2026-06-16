from __future__ import annotations

import unittest

import pandas as pd


class WalkForwardTest(unittest.TestCase):
    def test_rolling_two_year_train_one_year_test_windows_do_not_overlap(self) -> None:
        from fintech_quant.training.walk_forward import rolling_windows

        windows = rolling_windows(
            dates=pd.date_range("2020-01-01", "2024-12-31", freq="D"),
            train_years=2,
            test_years=1,
        )

        self.assertEqual(len(windows), 3)
        first = windows[0]
        self.assertEqual(first.train_start.isoformat(), "2020-01-01")
        self.assertEqual(first.train_end.isoformat(), "2021-12-31")
        self.assertEqual(first.test_start.isoformat(), "2022-01-01")
        self.assertEqual(first.test_end.isoformat(), "2022-12-31")
        self.assertLess(first.train_end, first.test_start)

    def test_expanding_windows_keep_train_start_fixed(self) -> None:
        from fintech_quant.training.walk_forward import expanding_windows

        windows = expanding_windows(
            dates=pd.date_range("2020-01-01", "2024-12-31", freq="D"),
            initial_train_years=2,
            test_years=1,
        )

        self.assertEqual(len(windows), 3)
        self.assertEqual({window.train_start.isoformat() for window in windows}, {"2020-01-01"})
        self.assertEqual(windows[1].train_end.isoformat(), "2022-12-31")
        self.assertEqual(windows[1].test_start.isoformat(), "2023-01-01")

    def test_buy_and_hold_report_uses_only_out_of_sample_test_rows(self) -> None:
        from fintech_quant.training.walk_forward import WalkForwardWindow
        from fintech_quant.strategies.buy_and_hold import evaluate_buy_and_hold

        features = pd.DataFrame(
            {
                "代码": ["sh688001"] * 4,
                "date": ["2020-01-01", "2020-01-02", "2022-01-01", "2022-01-02"],
                "target_next_return_1d": [9.0, 9.0, 0.10, -0.05],
            }
        )
        window = WalkForwardWindow(
            name="sample",
            train_start=pd.Timestamp("2020-01-01").date(),
            train_end=pd.Timestamp("2021-12-31").date(),
            test_start=pd.Timestamp("2022-01-01").date(),
            test_end=pd.Timestamp("2022-12-31").date(),
        )

        result = evaluate_buy_and_hold(features, window)

        self.assertEqual(result.test_rows, 2)
        self.assertEqual(result.train_start.isoformat(), "2020-01-01")
        self.assertEqual(result.test_start.isoformat(), "2022-01-01")
        self.assertAlmostEqual(result.test_cumulative_return, 0.045)


if __name__ == "__main__":
    unittest.main()
