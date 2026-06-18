from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    market: str
    frequency: str
    execution_mode: str
    data_sources: tuple[str, ...] = field(default_factory=tuple)


def default_settings() -> Settings:
    return Settings(
        market="a_share",
        frequency="1d",
        execution_mode="paper",
        data_sources=("akshare", "tushare", "yahoo", "finnhub"),
    )
