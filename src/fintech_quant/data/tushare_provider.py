from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from datetime import date
from typing import Any

from fintech_quant.data.base import MarketDataProvider, normalize_daily_bar
from fintech_quant.data.errors import MissingProviderCredential, MissingProviderDependency, ProviderFetchError
from fintech_quant.data.symbols import normalize_a_share_symbol


class TushareProvider(MarketDataProvider):
    name = "tushare"

    def __init__(
        self,
        token: str | None = None,
        fetcher: Callable[..., Any] | None = None,
    ) -> None:
        self._token = token if token is not None else os.getenv("TUSHARE_TOKEN", "")
        self._fetcher = fetcher

    def history(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        if not self._token.strip():
            raise MissingProviderCredential("TUSHARE_TOKEN is required for TushareProvider")
        normalized_symbol = normalize_a_share_symbol(symbol)
        rows = self._fetch(normalized_symbol, start, end)
        try:
            return [normalize_daily_bar(normalized_symbol, row, self.name) for row in rows]
        except Exception as exc:
            raise ProviderFetchError(
                f"tushare history fetch failed for {normalized_symbol} between {start.isoformat()} and {end.isoformat()}"
            ) from exc

    def _fetch(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        if self._fetcher is not None:
            return self._run_fetch(symbol, start, end, self._fetcher)

        try:
            ts = importlib.import_module("tushare")
        except ImportError as exc:
            raise MissingProviderDependency("tushare is required for TushareProvider") from exc

        return self._run_fetch(symbol, start, end, lambda **_: _load_daily_rows(ts, symbol, start, end, self._token))

    def _run_fetch(
        self,
        symbol: str,
        start: date,
        end: date,
        fetcher: Callable[..., Any],
    ) -> list[dict[str, Any]]:
        try:
            return list(fetcher(symbol=symbol, start=start, end=end, token=self._token))
        except Exception as exc:
            raise ProviderFetchError(
                f"tushare history fetch failed for {symbol} between {start.isoformat()} and {end.isoformat()}"
            ) from exc


def _load_daily_rows(ts: Any, symbol: str, start: date, end: date, token: str) -> list[dict[str, Any]]:
    pro = ts.pro_api(token)
    frame = pro.daily(
        ts_code=symbol,
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
    )
    return frame.to_dict(orient="records")
