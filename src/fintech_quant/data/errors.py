from __future__ import annotations


class DataProviderError(RuntimeError):
    """Base error for market data provider failures."""


class MissingProviderCredential(DataProviderError):
    """Raised when a provider needs a credential that is not configured."""


class MissingProviderDependency(DataProviderError):
    """Raised when an optional provider package is not installed."""


class ProviderFetchError(DataProviderError):
    """Raised when a provider fetch fails at runtime."""


class UnknownDataProvider(DataProviderError):
    """Raised when a requested provider is not registered."""
