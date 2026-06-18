from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from fintech_quant.data.base import MarketDataProvider


@dataclass(frozen=True)
class AkShareProvider(MarketDataProvider):
    name = "akshare"
    adjust: str = ""

    def history(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        try:
            import akshare as ak
        except ModuleNotFoundError as exc:
            raise RuntimeError("Install AkShare with: python -m pip install -e '.[data]'") from exc

        raw_symbol = _akshare_symbol(symbol)
        frame = ak.stock_zh_a_hist(
            symbol=raw_symbol,
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust=self.adjust,
        )

        rows: list[dict[str, Any]] = []
        for record in frame.to_dict("records"):
            rows.append(
                {
                    "symbol": symbol,
                    "date": str(record["日期"]),
                    "open": float(record["开盘"]),
                    "high": float(record["最高"]),
                    "low": float(record["最低"]),
                    "close": float(record["收盘"]),
                    "volume": float(record["成交量"]),
                    "amount": float(record.get("成交额", 0.0)),
                    "turnover": float(record.get("换手率", 0.0)),
                }
            )
        return rows


def _akshare_symbol(symbol: str) -> str:
    normalized = symbol.lower().strip()
    if normalized.startswith(("sh", "sz", "bj")):
        return normalized[2:]
    return normalized
