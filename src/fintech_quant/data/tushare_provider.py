from __future__ import annotations

import os
from collections.abc import Callable
from datetime import date
from typing import Any

from fintech_quant.data.base import MarketDataProvider, normalize_daily_bar
from fintech_quant.data.errors import MissingProviderCredential
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
        return [normalize_daily_bar(normalized_symbol, row, self.name) for row in rows]

    def _fetch(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        if self._fetcher is not None:
            return list(self._fetcher(symbol=symbol, start=start, end=end, token=self._token))
        import tushare as ts

        pro = ts.pro_api(self._token)
        frame = pro.daily(
            ts_code=symbol,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        return frame.to_dict(orient="records")
