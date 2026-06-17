from __future__ import annotations

import unittest

import pandas as pd


class FeatureEngineeringTest(unittest.TestCase):
    def test_daily_indicators_use_only_current_and_past_rows(self) -> None:
        from fintech_quant.features.indicators import build_daily_feature_frame

        base = pd.DataFrame(
            {
                "代码": ["sh688001"] * 6,
                "名称": ["A"] * 6,
                "date": pd.date_range("2024-01-01", periods=6, freq="D").astype(str),
                "open": [10, 11, 12, 13, 14, 15],
                "high": [11, 12, 13, 14, 15, 1000],
                "low": [9, 10, 11, 12, 13, 1],
                "close": [10, 11, 12, 13, 14, 1000],
                "volume": [100, 110, 120, 130, 140, 999],
                "after_volume": [0, 0, 0, 0, 0, 0],
                "after_amount": [0, 0, 0, 0, 0, 0],
                "outstanding_share": [1000] * 6,
                "turnover": [0.1] * 6,
            }
        )
        changed_future = base.copy()
        changed_future.loc[5, ["high", "low", "close", "volume"]] = [16, 14, 15, 150]

        base_features = build_daily_feature_frame(base)
        changed_features = build_daily_feature_frame(changed_future)

        feature_columns = [
            "return_1d",
            "return_5d",
            "ma_5",
            "volume_ma_5",
            "rsi_14",
            "macd",
        ]
        pd.testing.assert_frame_equal(
            base_features.loc[:4, ["代码", "date", *feature_columns]],
            changed_features.loc[:4, ["代码", "date", *feature_columns]],
            check_dtype=False,
        )

    def test_daily_indicators_create_three_action_labels_from_next_return(self) -> None:
        from fintech_quant.features.indicators import build_daily_feature_frame

        frame = pd.DataFrame(
            {
                "代码": ["sh688001"] * 4,
                "名称": ["A"] * 4,
                "date": pd.date_range("2024-01-01", periods=4, freq="D").astype(str),
                "open": [10, 12, 12, 11],
                "high": [10, 12, 12, 11],
                "low": [10, 12, 12, 11],
                "close": [10, 12, 12, 11],
                "volume": [100, 100, 100, 100],
                "after_volume": [0, 0, 0, 0],
                "after_amount": [0, 0, 0, 0],
                "outstanding_share": [1000] * 4,
                "turnover": [0.1] * 4,
            }
        )

        features = build_daily_feature_frame(frame)

        self.assertEqual(
            features["target_action"].tolist(),
            ["buy", "hold", "sell", "hold"],
        )
        self.assertTrue(pd.isna(features.loc[3, "target_next_return_1d"]))

    def test_daily_indicators_handle_flat_price_ranges(self) -> None:
        from fintech_quant.features.indicators import build_daily_feature_frame

        frame = pd.DataFrame(
            {
                "代码": ["sh688001"] * 3,
                "名称": ["A"] * 3,
                "date": pd.date_range("2024-01-01", periods=3, freq="D").astype(str),
                "open": [10, 10, 10],
                "high": [10, 10, 10],
                "low": [10, 10, 10],
                "close": [10, 10, 10],
                "volume": [100, 100, 100],
                "after_volume": [0, 0, 0],
                "after_amount": [0, 0, 0],
                "outstanding_share": [1000] * 3,
                "turnover": [0.1] * 3,
            }
        )

        features = build_daily_feature_frame(frame)

        self.assertEqual(features["close_position"].tolist(), [0.5, 0.5, 0.5])
        self.assertEqual(features["rsi_14"].tolist(), [50.0, 50.0, 50.0])

    def test_daily_indicators_add_trend_factors_for_rl_state(self) -> None:
        from fintech_quant.features.indicators import build_daily_feature_frame, feature_columns

        frame = pd.DataFrame(
            {
                "代码": ["sh688001"] * 65,
                "名称": ["A"] * 65,
                "date": pd.date_range("2024-01-01", periods=65, freq="D").astype(str),
                "open": list(range(10, 75)),
                "high": list(range(11, 76)),
                "low": list(range(9, 74)),
                "close": list(range(10, 75)),
                "volume": [100] * 65,
                "after_volume": [0] * 65,
                "after_amount": [0] * 65,
                "outstanding_share": [1000] * 65,
                "turnover": [0.1] * 65,
            }
        )

        features = build_daily_feature_frame(frame)

        for column in ("return_20d", "return_60d", "ma_20_slope", "ma_60_slope"):
            self.assertIn(column, features.columns)
            self.assertIn(column, feature_columns())
        self.assertGreater(features.loc[64, "return_20d"], 0)
        self.assertGreater(features.loc[64, "ma_20_slope"], 0)


if __name__ == "__main__":
    unittest.main()
