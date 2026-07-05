from __future__ import annotations

from dataclasses import dataclass

from fintech_quant.data.symbols import normalize_a_share_symbol


@dataclass(frozen=True)
class ScoreInput:
    symbol: str
    pe: float | None = None
    pb: float | None = None
    roe: float | None = None
    growth: float | None = None
    close_above_ma20: bool | None = None
    close_above_ma60: bool | None = None
    relative_strength: float | None = None
    rsi: float | None = None
    macd_positive: bool | None = None
    volume_confirmed: bool | None = None
    main_net_inflow: float | None = None
    main_outflow_days: int | None = None
    margin_financing_positive: bool | None = None
    limit_up_streak: int | None = None
    dragon_tiger_positive: bool | None = None
    negative_event_count: int | None = None


@dataclass(frozen=True)
class ComponentScore:
    name: str
    score: float
    max_score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class StockScore:
    symbol: str
    total: float
    components: dict[str, ComponentScore]
    confidence: float
    missing_fields: tuple[str, ...]


def factor_pipeline_name() -> str:
    return "a_share_daily_factor_pipeline_v0"


def score_stock(score_input: ScoreInput) -> StockScore:
    missing: list[str] = []
    components = {
        "fundamental": _fundamental_score(score_input, missing),
        "technical": _technical_score(score_input, missing),
        "capital_flow": _capital_flow_score(score_input, missing),
        "sentiment": _sentiment_score(score_input, missing),
    }
    total = round(sum(component.score for component in components.values()), 4)
    expected_fields = 16
    confidence = round((expected_fields - len(set(missing))) / expected_fields, 4)
    return StockScore(
        symbol=normalize_a_share_symbol(score_input.symbol),
        total=total,
        components=components,
        confidence=max(0.0, confidence),
        missing_fields=tuple(sorted(set(missing))),
    )


def _fundamental_score(score_input: ScoreInput, missing: list[str]) -> ComponentScore:
    score = 0.0
    reasons: list[str] = []
    if score_input.pe is None:
        missing.append("pe")
    elif 0 < score_input.pe <= 30:
        score += 8.75
        reasons.append("PE is within the sanity band.")
    if score_input.pb is None:
        missing.append("pb")
    elif 0 < score_input.pb <= 3:
        score += 8.75
        reasons.append("PB is within the sanity band.")
    if score_input.roe is None:
        missing.append("roe")
    elif score_input.roe >= 0.12:
        score += 8.75
        reasons.append("ROE is above 12%.")
    if score_input.growth is None:
        missing.append("growth")
    elif score_input.growth >= 0.08:
        score += 8.75
        reasons.append("Growth is above 8%.")
    return ComponentScore("fundamental", score, 35.0, tuple(reasons))


def _technical_score(score_input: ScoreInput, missing: list[str]) -> ComponentScore:
    score = 0.0
    reasons: list[str] = []
    score += _bool_points(
        score_input.close_above_ma20,
        "close_above_ma20",
        4.0,
        missing,
        reasons,
    )
    score += _bool_points(
        score_input.close_above_ma60,
        "close_above_ma60",
        4.0,
        missing,
        reasons,
    )
    if score_input.relative_strength is None:
        missing.append("relative_strength")
    elif score_input.relative_strength >= 0.6:
        score += 5.0
        reasons.append("Relative strength ranks in the top 40% of the universe.")
    if score_input.rsi is None:
        missing.append("rsi")
    elif 45 <= score_input.rsi <= 65:
        score += 4.0
        reasons.append("RSI is in a healthy trend range.")
    score += _bool_points(
        score_input.macd_positive,
        "macd_positive",
        4.0,
        missing,
        reasons,
    )
    score += _bool_points(
        score_input.volume_confirmed,
        "volume_confirmed",
        4.0,
        missing,
        reasons,
    )
    return ComponentScore("technical", score, 25.0, tuple(reasons))


def _capital_flow_score(score_input: ScoreInput, missing: list[str]) -> ComponentScore:
    score = 0.0
    reasons: list[str] = []
    if score_input.main_net_inflow is None:
        missing.append("main_net_inflow")
    elif score_input.main_net_inflow > 0:
        score += 10.0
        reasons.append("Main capital is net inflow.")
    if score_input.main_outflow_days is None:
        missing.append("main_outflow_days")
    elif score_input.main_outflow_days <= 3:
        score += 7.5
        reasons.append("Main capital outflow is not persistent.")
    score += _bool_points(
        score_input.margin_financing_positive,
        "margin_financing_positive",
        7.5,
        missing,
        reasons,
    )
    return ComponentScore("capital_flow", score, 25.0, tuple(reasons))


def _sentiment_score(score_input: ScoreInput, missing: list[str]) -> ComponentScore:
    score = 0.0
    reasons: list[str] = []
    if score_input.limit_up_streak is None:
        missing.append("limit_up_streak")
    elif score_input.limit_up_streak >= 1:
        score += 5.0
        reasons.append("Limit-up streak shows positive momentum.")
    score += _bool_points(
        score_input.dragon_tiger_positive,
        "dragon_tiger_positive",
        5.0,
        missing,
        reasons,
    )
    if score_input.negative_event_count is None:
        missing.append("negative_event_count")
    elif score_input.negative_event_count == 0:
        score += 5.0
        reasons.append("No negative event was provided.")
    return ComponentScore("sentiment", score, 15.0, tuple(reasons))


def _bool_points(
    value: bool | None,
    field_name: str,
    points: float,
    missing: list[str],
    reasons: list[str],
) -> float:
    if value is None:
        missing.append(field_name)
        return 0.0
    if value:
        reasons.append(f"{field_name} is positive.")
        return points
    return 0.0
