from __future__ import annotations

from datetime import date


def test_cninfo_rights_issue_is_preserved_as_explicit_action() -> None:
    from fintech_quant.data.corporate_action_store import materialize_cninfo_corporate_actions

    actions = materialize_cninfo_corporate_actions(
        [
            {
                "symbol": "600030.SH",
                "_action_type": "rights_issue",
                "公告日期": "2022-01-14",
                "股权登记日": "2022-01-18",
                "除权基准日": "2022-01-27",
                "配股上市日": "2022-02-15",
                "配股比例": 1.5,
                "配股价格": 14.43,
            }
        ],
        start=date(2021, 1, 1),
        end=date(2023, 1, 1),
    )

    assert len(actions) == 1
    assert actions[0].action_type == "rights_issue"
    assert actions[0].rights_ratio == 0.15
    assert actions[0].rights_price == 14.43
    assert actions[0].listing_date == date(2022, 2, 15)


def test_cninfo_terms_are_normalized_from_per_ten_shares() -> None:
    from fintech_quant.data.corporate_action_store import materialize_cninfo_corporate_actions

    actions = materialize_cninfo_corporate_actions(
        [
            {
                "symbol": "000001.SZ",
                "实施方案公告日期": "2026-06-05",
                "股权登记日": "2026-06-11",
                "除权日": "2026-06-12",
                "派息比例": 3.6,
                "送股比例": 2.0,
                "转增比例": 1.0,
            }
        ],
        start=date(2026, 1, 1),
        end=date(2026, 12, 31),
    )

    assert len(actions) == 1
    assert actions[0].symbol == "000001.SZ"
    assert actions[0].ex_date == date(2026, 6, 12)
    assert actions[0].cash_dividend_per_share == 0.36
    assert actions[0].share_multiplier == 1.3
    assert actions[0].source == "akshare_cninfo_dividend"


def test_cninfo_actions_outside_research_dates_are_excluded() -> None:
    from fintech_quant.data.corporate_action_store import materialize_cninfo_corporate_actions

    actions = materialize_cninfo_corporate_actions(
        [
            {
                "symbol": "000001.SZ",
                "除权日": "2025-06-12",
                "派息比例": 3.6,
            }
        ],
        start=date(2026, 1, 1),
        end=date(2026, 12, 31),
    )

    assert actions == []


def test_sina_fallback_terms_use_the_same_normalized_contract() -> None:
    from fintech_quant.data.corporate_action_store import materialize_cninfo_corporate_actions

    actions = materialize_cninfo_corporate_actions(
        [
            {
                "symbol": "600837.SH",
                "公告日期": "2024-10-11",
                "除权除息日": "2024-10-18",
                "派息": 0.3,
                "送股": 1.0,
                "转增": 0.0,
                "进度": "实施",
            }
        ],
        start=date(2024, 1, 1),
        end=date(2024, 12, 31),
    )

    assert len(actions) == 1
    assert actions[0].cash_dividend_per_share == 0.03
    assert actions[0].share_multiplier == 1.1
    assert actions[0].source == "akshare_sina_dividend"


def test_same_day_regular_and_special_dividends_are_combined() -> None:
    from fintech_quant.data.corporate_action_store import materialize_cninfo_corporate_actions

    rows = [
        {
            "symbol": "002352.SZ",
            "实施方案公告日期": "2024-10-31",
            "除权日": "2024-11-07",
            "派息比例": 4.0,
        },
        {
            "symbol": "002352.SZ",
            "实施方案公告日期": "2024-10-31",
            "除权日": "2024-11-07",
            "派息比例": 10.0,
        },
    ]

    actions = materialize_cninfo_corporate_actions(
        rows,
        start=date(2024, 1, 1),
        end=date(2024, 12, 31),
    )

    assert len(actions) == 1
    assert actions[0].cash_dividend_per_share == 1.4
