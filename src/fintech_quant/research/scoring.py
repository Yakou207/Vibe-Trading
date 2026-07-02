from __future__ import annotations

from datetime import date
from typing import Mapping, Sequence

from fintech_quant.features import ScoreInput, StockScore, score_stock
from fintech_quant.information import InformationRecord
from fintech_quant.research.dataset import FeatureRow, ResearchDataset, SupplementalRow


NEGATIVE_RISK_TAGS = frozenset(
    {
        "negative_announcement",
        "st_warning",
        "regulatory_risk",
        "pledge_risk",
        "goodwill_risk",
    }
)


def build_stock_scores(dataset: ResearchDataset) -> dict[tuple[date, str], StockScore]:
    scores: dict[tuple[date, str], StockScore] = {}
    for row in dataset.features:
        score_input = build_score_input(
            row,
            _supplement_for(dataset.fundamentals, row.symbol, row.trade_date),
            _supplement_for(dataset.capital_flow, row.symbol, row.trade_date),
            dataset.information_records,
        )
        scores[(row.trade_date, row.symbol)] = score_stock(score_input)
    return scores


def build_score_input(
    feature_row: FeatureRow,
    fundamentals: SupplementalRow | Mapping[str, object] | None = None,
    capital_flow: SupplementalRow | Mapping[str, object] | None = None,
    information_records: Sequence[InformationRecord] = (),
) -> ScoreInput:
    feature_values = feature_row.values
    fundamental_values = _values(fundamentals)
    capital_values = _values(capital_flow)
    return ScoreInput(
        symbol=feature_row.symbol,
        pe=_float_or_none(fundamental_values.get("pe")),
        pb=_float_or_none(fundamental_values.get("pb")),
        roe=_float_or_none(fundamental_values.get("roe")),
        growth=_float_or_none(fundamental_values.get("growth")),
        close_above_ma20=_bool_or_none(feature_values.get("close_above_ma20")),
        close_above_ma60=_bool_or_none(feature_values.get("close_above_ma60")),
        rsi=_float_or_none(feature_values.get("rsi14")),
        macd_positive=_bool_or_none(feature_values.get("macd_positive")),
        volume_confirmed=_volume_confirmed(feature_values),
        main_net_inflow=_float_or_none(capital_values.get("main_net_inflow")),
        main_outflow_days=_int_or_none(capital_values.get("main_outflow_days")),
        margin_financing_positive=_bool_or_none(capital_values.get("margin_financing_positive")),
        limit_up_streak=_int_or_none(feature_values.get("limit_up_streak")),
        dragon_tiger_positive=_first_present(
            _bool_or_none(feature_values.get("dragon_tiger_positive")),
            _dragon_tiger_positive(feature_row.symbol, feature_row.trade_date, information_records),
        ),
        negative_event_count=_negative_event_count(
            feature_row.symbol,
            feature_row.trade_date,
            information_records,
            _text_or_none(feature_values.get("sector")),
        ),
    )


def _supplement_for(
    rows: Mapping[tuple[str, date | None], SupplementalRow],
    symbol: str,
    trade_date: date,
) -> SupplementalRow | None:
    return rows.get((symbol, trade_date)) or rows.get((symbol, None))


def _values(row: SupplementalRow | Mapping[str, object] | None) -> Mapping[str, object]:
    if row is None:
        return {}
    if isinstance(row, SupplementalRow):
        return row.values
    return row


def _negative_event_count(
    symbol: str,
    trade_date: date,
    records: Sequence[InformationRecord],
    sector: str | None = None,
) -> int:
    return sum(
        1
        for record in records
        if (record.normalized_symbol == symbol or (sector is not None and record.symbol is None and record.sector == sector))
        and record.published_at <= trade_date
        and any(tag in NEGATIVE_RISK_TAGS for tag in record.risk_tags)
    )


def _dragon_tiger_positive(
    symbol: str,
    trade_date: date,
    records: Sequence[InformationRecord],
) -> bool | None:
    matching_records = [
        record
        for record in records
        if record.normalized_symbol == symbol
        and record.published_at <= trade_date
        and "dragon_tiger" in record.risk_tags
    ]
    if not matching_records:
        return None

    latest_record = max(matching_records, key=lambda record: record.published_at)
    if "dragon_tiger_positive" in latest_record.risk_tags:
        return True
    if "dragon_tiger_negative" in latest_record.risk_tags:
        return False
    return None


def _first_present(*values: bool | None) -> bool | None:
    for value in values:
        if value is not None:
            return value
    return None


def _volume_confirmed(values: Mapping[str, object]) -> bool | None:
    volume = _float_or_none(values.get("volume"))
    return_1d = _float_or_none(values.get("return_1d"))
    if volume is None or return_1d is None:
        return None
    return volume > 0 and return_1d >= 0


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _bool_or_none(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return bool(value)


def _text_or_none(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)
