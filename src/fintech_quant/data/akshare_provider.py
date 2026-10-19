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

    def __init__(
        self,
        fetcher: Callable[..., Any] | None = None,
        *,
        backend: str = "eastmoney",
        adjust: str = "qfq",
    ) -> None:
        if backend not in {"eastmoney", "sina", "tencent"}:
            raise ValueError("AkShare backend must be eastmoney, sina, or tencent")
        if adjust not in {"qfq", "hfq", "none"}:
            raise ValueError("AkShare adjustment must be qfq, hfq, or none")
        self._fetcher = fetcher
        self._backend = backend
        self._adjust = adjust
        self.name = _provider_name(backend, adjust)

    def history(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        normalized_symbol = normalize_a_share_symbol(symbol)
        rows = self._fetch(normalized_symbol, start, end)
        try:
            return [normalize_daily_bar(normalized_symbol, row, self.name) for row in rows]
        except Exception as exc:
            raise ProviderFetchError(
                f"akshare history fetch failed for {normalized_symbol} between {start.isoformat()} and {end.isoformat()}"
            ) from exc

    def _fetch(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        if self._fetcher is not None:
            return self._run_fetch(symbol, start, end, self._fetcher)

        try:
            ak = importlib.import_module("akshare")
        except ImportError as exc:
            raise MissingProviderDependency("akshare is required for AkShareProvider") from exc

        return self._run_fetch(
            symbol,
            start,
            end,
            lambda **_: _load_hist_rows(
                ak,
                symbol,
                start,
                end,
                backend=self._backend,
                adjust=self._adjust,
            ),
        )

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


def _load_hist_rows(
    ak: Any,
    symbol: str,
    start: date,
    end: date,
    *,
    backend: str,
    adjust: str,
) -> list[dict[str, Any]]:
    code = symbol.split(".")[0]
    api_adjust = "" if adjust == "none" else adjust
    if backend == "sina":
        exchange = symbol.split(".")[1].lower()
        try:
            frame = ak.stock_zh_a_daily(
                symbol=f"{exchange}{code}",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust=api_adjust,
            )
        except Exception:
            # Sina raises instead of returning nothing when a range has no trades (e.g. a long
            # suspension). Treat the range as empty only if Tencent independently confirms it has
            # no trades; otherwise keep the failure. Tencent prices are never substituted.
            confirmation = ak.stock_zh_a_hist_tx(
                symbol=f"{exchange}{code}",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust=api_adjust,
                timeout=30,
            )
            if len(confirmation) == 0:
                return []
            raise
    elif backend == "tencent":
        exchange = symbol.split(".")[1].lower()
        frame = ak.stock_zh_a_hist_tx(
            symbol=f"{exchange}{code}",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust=api_adjust,
            timeout=30,
        )
        rows = frame.to_dict(orient="records")
        for row in rows:
            volume = float(row["amount"]) * 100.0
            row["volume"] = volume
            row["amount"] = float(row["close"]) * volume
        return rows
    else:
        frame = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust=api_adjust,
        )
    return frame.to_dict(orient="records")


def _provider_name(backend: str, adjust: str) -> str:
    if backend == "eastmoney":
        if adjust == "qfq":
            return "akshare"
        return f"akshare-eastmoney-{'hfq' if adjust == 'hfq' else 'unadjusted'}"
    if backend == "sina":
        return f"akshare-sina-{adjust if adjust != 'none' else 'unadjusted'}"
    suffix = adjust if adjust != "none" else "unadjusted"
    return f"akshare-tencent-{suffix}-estimated-turnover"
