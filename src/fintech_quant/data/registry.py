from __future__ import annotations

from datetime import date

from fintech_quant.data.base import MarketDataProvider
from fintech_quant.data.errors import UnknownDataProvider
from fintech_quant.data.symbols import normalize_a_share_symbol


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, MarketDataProvider] = {}

    def register(self, provider: MarketDataProvider) -> None:
        self._providers[provider.name] = provider

    def get(self, source: str) -> MarketDataProvider:
        if source == "auto":
            source = "akshare"
        try:
            return self._providers[source]
        except KeyError as exc:
            raise UnknownDataProvider(f"Unknown data provider: {source}") from exc

    def history(
        self,
        symbol: str,
        start: date,
        end: date,
        source: str = "auto",
    ) -> list[dict[str, object]]:
        normalized_symbol = normalize_a_share_symbol(symbol)
        return self.get(source).history(normalized_symbol, start, end)
