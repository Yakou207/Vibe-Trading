from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from fintech_quant.data.symbols import normalize_a_share_symbol


@dataclass(frozen=True)
class CorporateAction:
    symbol: str
    ex_date: date
    cash_dividend_per_share: float = 0.0
    share_multiplier: float = 1.0
    source: str = ""
    action_type: str = "distribution"
    rights_ratio: float = 0.0
    rights_price: float = 0.0
    listing_date: date | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", normalize_a_share_symbol(self.symbol))
        if not self.source.strip():
            raise ValueError("corporate action source is required")
        if self.action_type not in {"distribution", "rights_issue"}:
            raise ValueError("unsupported corporate action type")
        if not math.isfinite(self.cash_dividend_per_share) or self.cash_dividend_per_share < 0:
            raise ValueError("cash_dividend_per_share must be finite and non-negative")
        if not math.isfinite(self.share_multiplier) or self.share_multiplier <= 0:
            raise ValueError("share_multiplier must be finite and positive")
        if self.action_type == "rights_issue":
            if self.rights_ratio <= 0 or self.rights_price <= 0:
                raise ValueError("rights issue requires positive ratio and price")
            if self.listing_date is None or self.listing_date < self.ex_date:
                raise ValueError("rights issue listing date must not precede ex-date")
        elif self.cash_dividend_per_share == 0 and self.share_multiplier == 1:
            raise ValueError("corporate action must change cash or shares")


@dataclass(frozen=True)
class AppliedCorporateAction:
    symbol: str
    ex_date: date
    cash_dividend_per_share: float
    share_multiplier: float
    shares_before: int
    shares_after: int
    cash_delta: float
    source: str
    action_type: str = "distribution"
    rights_ratio: float = 0.0
    rights_price: float = 0.0
    rights_issue_policy: str | None = None


def load_corporate_actions_csv(path: Path) -> list[CorporateAction]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    actions = [
        CorporateAction(
            symbol=str(row.get("symbol", "")),
            ex_date=date.fromisoformat(str(row.get("ex_date", ""))),
            cash_dividend_per_share=_float_or_default(
                row.get("cash_dividend_per_share"),
                0.0,
            ),
            share_multiplier=_float_or_default(row.get("share_multiplier"), 1.0),
            source=str(row.get("source", "")),
            action_type=str(row.get("action_type") or "distribution"),
            rights_ratio=_float_or_default(row.get("rights_ratio"), 0.0),
            rights_price=_float_or_default(row.get("rights_price"), 0.0),
            listing_date=(
                date.fromisoformat(str(row["listing_date"])) if row.get("listing_date") else None
            ),
        )
        for row in rows
    ]
    if not actions:
        raise ValueError("corporate-action CSV must contain at least one row")
    return sorted(actions, key=lambda item: (item.ex_date, item.symbol))


def _float_or_default(value: object, default: float) -> float:
    return default if value in (None, "") else float(value)
