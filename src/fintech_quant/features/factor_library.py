from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class FactorSpec:
    name: str
    group: str
    description: str


def default_factor_specs() -> list[FactorSpec]:
    return [
        FactorSpec("return_5d", "momentum", "Five-day return momentum."),
        FactorSpec("return_20d", "momentum", "Twenty-day return momentum."),
        FactorSpec("return_60d", "momentum", "Sixty-day return momentum."),
        FactorSpec("macd_hist", "momentum", "MACD histogram momentum."),
        FactorSpec("close_to_ma_20", "trend", "Close price versus 20-day moving average."),
        FactorSpec("close_to_ma_60", "trend", "Close price versus 60-day moving average."),
        FactorSpec("ma_20_slope", "trend", "Twenty-day moving average slope."),
        FactorSpec("ma_60_slope", "trend", "Sixty-day moving average slope."),
        FactorSpec("volatility_20", "risk", "Twenty-day realized volatility."),
        FactorSpec("high_low_range", "risk", "Daily high-low range ratio."),
        FactorSpec("volume_ratio_20", "volume", "Volume versus 20-day average volume."),
        FactorSpec("turnover", "volume", "Daily turnover."),
        FactorSpec("rsi_14", "oscillator", "Fourteen-day RSI oscillator."),
        FactorSpec("close_position", "oscillator", "Close location inside the daily range."),
    ]


def available_factor_specs(features: pd.DataFrame) -> list[FactorSpec]:
    columns = set(features.columns)
    return [spec for spec in default_factor_specs() if spec.name in columns]


def factor_names(specs: list[FactorSpec]) -> list[str]:
    return [spec.name for spec in specs]
