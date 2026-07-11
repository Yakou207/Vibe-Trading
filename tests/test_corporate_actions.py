from __future__ import annotations

from datetime import date


def test_load_corporate_actions_normalizes_per_ten_share_terms(tmp_path) -> None:
    from fintech_quant.backtesting import load_corporate_actions_csv

    path = tmp_path / "corporate_actions.csv"
    path.write_text(
        "symbol,ex_date,cash_dividend_per_share,share_multiplier,source\n"
        "000001,2026-06-12,0.36,1.2,cninfo\n",
        encoding="utf-8",
    )

    actions = load_corporate_actions_csv(path)

    assert len(actions) == 1
    assert actions[0].symbol == "000001.SZ"
    assert actions[0].ex_date == date(2026, 6, 12)
    assert actions[0].cash_dividend_per_share == 0.36
    assert actions[0].share_multiplier == 1.2
    assert actions[0].source == "cninfo"
