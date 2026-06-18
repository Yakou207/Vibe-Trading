from __future__ import annotations

import re

_A_SHARE_RE = re.compile(r"^(?P<code>\d{6})(?:\.(?P<exchange>SH|SZ|BJ))?$", re.IGNORECASE)


def infer_a_share_exchange(code: str) -> str:
    normalized = code.strip()
    if len(normalized) != 6 or not normalized.isdigit():
        raise ValueError(f"Invalid A-share code: {code!r}")
    if normalized.startswith(("60", "68", "90")):
        return "SH"
    if normalized.startswith(("00", "30", "20")):
        return "SZ"
    if normalized.startswith(("43", "83", "87", "92")):
        return "BJ"
    raise ValueError(f"Cannot infer A-share exchange for code: {code!r}")


def normalize_a_share_symbol(symbol: str) -> str:
    raw = symbol.strip().upper()
    match = _A_SHARE_RE.match(raw)
    if not match:
        raise ValueError(f"Invalid A-share symbol: {symbol!r}")
    code = match.group("code")
    exchange = match.group("exchange") or infer_a_share_exchange(code)
    return f"{code}.{exchange.upper()}"
