from __future__ import annotations


class DataProviderError(RuntimeError):
    """Base error for market data provider failures."""


class MissingProviderCredential(DataProviderError):
    """Raised when a provider needs a credential that is not configured."""


class UnknownDataProvider(DataProviderError):
    """Raised when a requested provider is not registered."""
