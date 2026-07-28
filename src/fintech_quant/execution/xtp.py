"""ZTS XTP constants and symbol mapping.

Values mirror ``xtp_api_data_type.h`` from the official API 2.2.50.8 bindings.
This module is import-safe everywhere: it never touches the XTP shared
libraries, so tests run on macOS while the bridge itself runs in the
linux/amd64 container.
"""

from __future__ import annotations

from fintech_quant.data.symbols import normalize_a_share_symbol

XTP_MARKET_SZ = 1
XTP_MARKET_SH = 2
XTP_MARKET_BJ = 3

XTP_PRICE_LIMIT = 1
XTP_SIDE_BUY = 1
XTP_SIDE_SELL = 2
XTP_BUSINESS_CASH = 0

# XTP_ORDER_STATUS_TYPE values that never change again: all-traded,
# part-traded-then-cancelled, cancelled, rejected.
XTP_FINAL_ORDER_STATUSES = frozenset({1, 3, 5, 6})

_EXCHANGE_TO_MARKET = {"SZ": XTP_MARKET_SZ, "SH": XTP_MARKET_SH, "BJ": XTP_MARKET_BJ}
_MARKET_TO_EXCHANGE = {market: exchange for exchange, market in _EXCHANGE_TO_MARKET.items()}


def to_xtp_symbol(symbol: str) -> tuple[str, int]:
    """``"600000.SH"`` -> ``("600000", 2)``."""
    code, exchange = normalize_a_share_symbol(symbol).split(".")
    return code, _EXCHANGE_TO_MARKET[exchange]


def from_xtp_symbol(ticker: str, market: int) -> str:
    """``("600000", 2)`` -> ``"600000.SH"``."""
    exchange = _MARKET_TO_EXCHANGE.get(int(market))
    if exchange is None:
        raise ValueError(f"unsupported XTP market: {market!r}")
    return normalize_a_share_symbol(f"{str(ticker).strip()}.{exchange}")
