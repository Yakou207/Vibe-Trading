from __future__ import annotations

import unittest

import pandas as pd


class FactorLibraryTest(unittest.TestCase):
    def test_default_factor_library_groups_research_factors(self) -> None:
        from fintech_quant.features.factor_library import default_factor_specs

        specs = default_factor_specs()
        spec_by_name = {spec.name: spec for spec in specs}

        self.assertIn("rsi_14", spec_by_name)
        self.assertEqual(spec_by_name["rsi_14"].group, "oscillator")
        self.assertIn("macd_hist", spec_by_name)
        self.assertEqual(spec_by_name["macd_hist"].group, "momentum")

    def test_available_factor_specs_skip_missing_columns(self) -> None:
        from fintech_quant.features.factor_library import available_factor_specs

        frame = pd.DataFrame(
            {
                "代码": ["sh688001"],
                "date": ["2024-01-02"],
                "rsi_14": [55.0],
                "target_next_return_1d": [0.01],
            }
        )

        specs = available_factor_specs(frame)

        self.assertEqual([spec.name for spec in specs], ["rsi_14"])

    def test_factor_diagnostics_adds_metadata_and_rank_ic_without_scipy(self) -> None:
        from fintech_quant.features.factor_diagnostics import factor_diagnostics
        from fintech_quant.features.factor_library import FactorSpec

        features = pd.DataFrame(
            {
                "factor_a": [1.0, 2.0, 3.0],
                "factor_b": [3.0, 2.0, 1.0],
                "target_next_return_1d": [0.01, 0.02, 0.03],
            }
        )
        specs = [
            FactorSpec("factor_a", "test", "Ascending factor"),
            FactorSpec("factor_b", "test", "Descending factor"),
        ]

        diagnostics = factor_diagnostics(features, ["factor_a", "factor_b"], factor_specs=specs)

        self.assertAlmostEqual(diagnostics["factor_a"]["rank_ic"], 1.0)
        self.assertAlmostEqual(diagnostics["factor_b"]["rank_ic"], -1.0)
        self.assertEqual(diagnostics["factor_a"]["group"], "test")
        self.assertEqual(diagnostics["factor_a"]["direction"], "positive")
        self.assertEqual(diagnostics["factor_b"]["direction"], "negative")


if __name__ == "__main__":
    unittest.main()
