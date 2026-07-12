from __future__ import annotations

import math
from datetime import date
from typing import Mapping, Sequence

from fintech_quant.backtesting.corporate_actions import CorporateAction


def materialize_cninfo_corporate_actions(
    rows: Sequence[Mapping[str, object]],
    *,
    start: date,
    end: date,
) -> list[CorporateAction]:
    actions_by_key: dict[tuple[str, date, str], CorporateAction] = {}
    for row in rows:
        if row.get("_action_type") == "rights_issue":
            ex_date = _optional_date(row.get("除权基准日"))
            if ex_date is None or not start <= ex_date <= end:
                continue
            announcement_date = _optional_date(row.get("公告日期"))
            if announcement_date is not None and announcement_date > ex_date:
                raise ValueError("rights-issue announcement date is after ex-date")
            action = CorporateAction(
                symbol=str(row.get("symbol", "")),
                ex_date=ex_date,
                action_type="rights_issue",
                rights_ratio=round(float(row["配股比例"]) / 10.0, 8),
                rights_price=float(row["配股价格"]),
                listing_date=_optional_date(row.get("配股上市日")),
                source="akshare_cninfo_rights_issue",
            )
            actions_by_key[(action.symbol, action.ex_date, action.action_type)] = action
            continue
        is_sina = "除权除息日" in row and "除权日" not in row
        if is_sina and str(row.get("进度", "实施")).strip() != "实施":
            continue
        ex_date = _optional_date(row.get("除权除息日" if is_sina else "除权日"))
        if ex_date is None or not start <= ex_date <= end:
            continue
        announcement_date = _optional_date(row.get("公告日期" if is_sina else "实施方案公告日期"))
        if announcement_date is not None and announcement_date > ex_date:
            raise ValueError("corporate-action announcement date is after ex-date")
        cash_per_ten = _optional_float(row.get("派息" if is_sina else "派息比例")) or 0.0
        bonus_per_ten = _optional_float(row.get("送股" if is_sina else "送股比例")) or 0.0
        transfer_per_ten = _optional_float(row.get("转增" if is_sina else "转增比例")) or 0.0
        cash_per_share = round(cash_per_ten / 10.0, 8)
        share_multiplier = round(1.0 + (bonus_per_ten + transfer_per_ten) / 10.0, 8)
        if cash_per_share == 0 and share_multiplier == 1:
            continue
        action = CorporateAction(
            symbol=str(row.get("symbol", "")),
            ex_date=ex_date,
            cash_dividend_per_share=cash_per_share,
            share_multiplier=share_multiplier,
            source="akshare_sina_dividend" if is_sina else "akshare_cninfo_dividend",
        )
        key = (action.symbol, action.ex_date, action.action_type)
        previous = actions_by_key.get(key)
        if previous is not None:
            action = CorporateAction(
                symbol=action.symbol,
                ex_date=action.ex_date,
                cash_dividend_per_share=round(
                    previous.cash_dividend_per_share + action.cash_dividend_per_share,
                    8,
                ),
                share_multiplier=round(
                    1.0 + (previous.share_multiplier - 1.0) + (action.share_multiplier - 1.0),
                    8,
                ),
                source=(
                    previous.source
                    if previous.source == action.source
                    else f"{previous.source}+{action.source}"
                ),
            )
        actions_by_key[key] = action
    return sorted(actions_by_key.values(), key=lambda item: (item.ex_date, item.symbol))


def _optional_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.lower() in {"nan", "nat", "none"}:
        return None
    return date.fromisoformat(text[:10])


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    result = float(value)
    return result if math.isfinite(result) else None
