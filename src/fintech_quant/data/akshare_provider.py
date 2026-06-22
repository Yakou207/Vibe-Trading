from __future__ import annotations

import importlib
from collections.abc import Callable
from datetime import date
from typing import Any

from fintech_quant.data.base import MarketDataProvider, normalize_daily_bar
from fintech_quant.data.errors import MissingProviderDependency, ProviderFetchError
from fintech_quant.data.symbols import normalize_a_share_symbol


class AkShareProvider(MarketDataProvider):
    name = "akshare"

    def __init__(self, fetcher: Callable[..., Any] | None = None) -> None:
        self._fetcher = fetcher

    def history(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        normalized_symbol = normalize_a_share_symbol(symbol)
        rows = self._fetch(normalized_symbol, start, end)
        return [normalize_daily_bar(normalized_symbol, row, self.name) for row in rows]

    def _fetch(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        if self._fetcher is not None:
            return self._run_fetch(symbol, start, end, self._fetcher)

        try:
            ak = importlib.import_module("akshare")
        except ImportError as exc:
            raise MissingProviderDependency("akshare is required for AkShareProvider") from exc

        return self._run_fetch(symbol, start, end, lambda **_: _load_hist_rows(ak, symbol, start, end))

    def _run_fetch(
        self,
        symbol: str,
        start: date,
        end: date,
        fetcher: Callable[..., Any],
    ) -> list[dict[str, Any]]:
        try:
            return list(fetcher(symbol=symbol, start=start, end=end))
        except Exception as exc:
            raise ProviderFetchError(
                f"akshare history fetch failed for {symbol} between {start.isoformat()} and {end.isoformat()}"
            ) from exc


def _load_hist_rows(ak: Any, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
    code = symbol.split(".")[0]
    frame = ak.stock_zh_a_hist(
        symbol=code,
        period="daily",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        adjust="qfq",
    )
    return frame.to_dict(orient="records")
