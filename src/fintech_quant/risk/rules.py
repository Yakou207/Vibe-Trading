from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RiskAction(Enum):
    NONE = "none"
    WATCH = "watch"
    REDUCE = "reduce"
    LIQUIDATE = "liquidate"


_ACTION_RANK = {
    RiskAction.NONE: 0,
    RiskAction.WATCH: 1,
    RiskAction.REDUCE: 2,
    RiskAction.LIQUIDATE: 3,
}


@dataclass(frozen=True)
class RiskLimits:
    max_position_weight: float = 0.08
    max_portfolio_drawdown: float = 0.15
    max_single_position_drawdown: float = 0.08
    max_goodwill_ratio: float = 0.30
    max_pledge_ratio: float = 0.50
    max_main_outflow_days: int = 3
    broad_market_drop_threshold: int = 15


@dataclass(frozen=True)
class RiskRuleCatalogItem:
    layer: str
    rule: str
    action: RiskAction
    threshold: str
    message: str


RISK_RULE_CATALOG: tuple[RiskRuleCatalogItem, ...] = (
    RiskRuleCatalogItem(
        layer="single_stock_negative",
        rule="position_weight",
        action=RiskAction.REDUCE,
        threshold="position_weight > max_position_weight",
        message="Single position weight exceeded concentration threshold.",
    ),
    RiskRuleCatalogItem(
        layer="portfolio_drawdown",
        rule="portfolio_drawdown",
        action=RiskAction.LIQUIDATE,
        threshold="portfolio_drawdown >= max_portfolio_drawdown",
        message="Portfolio drawdown reached liquidation threshold.",
    ),
    RiskRuleCatalogItem(
        layer="single_stock_negative",
        rule="single_position_drawdown",
        action=RiskAction.REDUCE,
        threshold="single_position_drawdown > max_single_position_drawdown",
        message="Single position drawdown exceeded risk threshold.",
    ),
    RiskRuleCatalogItem(
        layer="single_stock_negative",
        rule="st_warning",
        action=RiskAction.REDUCE,
        threshold="st_warning is true",
        message="ST warning is active for the stock.",
    ),
    RiskRuleCatalogItem(
        layer="single_stock_negative",
        rule="negative_event_count",
        action=RiskAction.WATCH,
        threshold="negative_event_count > 0",
        message="Negative stock-specific information is present.",
    ),
    RiskRuleCatalogItem(
        layer="single_stock_negative",
        rule="goodwill_ratio",
        action=RiskAction.WATCH,
        threshold="goodwill_ratio > max_goodwill_ratio",
        message="Goodwill ratio exceeded watch threshold.",
    ),
    RiskRuleCatalogItem(
        layer="single_stock_negative",
        rule="pledge_ratio",
        action=RiskAction.WATCH,
        threshold="pledge_ratio > max_pledge_ratio",
        message="Share pledge ratio exceeded watch threshold.",
    ),
    RiskRuleCatalogItem(
        layer="single_stock_negative",
        rule="main_outflow_days",
        action=RiskAction.WATCH,
        threshold="main_outflow_days > max_main_outflow_days",
        message="Main capital outflow continued beyond threshold.",
    ),
    RiskRuleCatalogItem(
        layer="broad_market_abnormal",
        rule="index_below_annual_ma",
        action=RiskAction.WATCH,
        threshold="index_below_annual_ma is true",
        message="Broad index is below the 250-day moving average.",
    ),
    RiskRuleCatalogItem(
        layer="systemic_risk",
        rule="broad_market_drop_gt_3pct_count",
        action=RiskAction.REDUCE,
        threshold="broad_market_drop_gt_3pct_count > broad_market_drop_threshold",
        message="More than 15 tracked names fell over 3% in one day.",
    ),
)

_RISK_RULES_BY_NAME = {item.rule: item for item in RISK_RULE_CATALOG}


@dataclass(frozen=True)
class RiskInput:
    position_weight: float = 0.0
    portfolio_drawdown: float = 0.0
    single_position_drawdown: float = 0.0
    st_warning: bool = False
    negative_event_count: int = 0
    goodwill_ratio: float = 0.0
    pledge_ratio: float = 0.0
    main_outflow_days: int = 0
    index_below_annual_ma: bool = False
    broad_market_drop_gt_3pct_count: int = 0


@dataclass(frozen=True)
class RiskWarning:
    layer: str
    rule: str
    action: RiskAction
    message: str


@dataclass(frozen=True)
class RiskEvaluation:
    action: RiskAction
    warnings: list[RiskWarning]


def evaluate_risk(
    risk_input: RiskInput,
    limits: RiskLimits = RiskLimits(),
) -> RiskEvaluation:
    warnings: list[RiskWarning] = []

    if risk_input.position_weight > limits.max_position_weight:
        warnings.append(_warning("position_weight"))

    if risk_input.portfolio_drawdown >= limits.max_portfolio_drawdown:
        warnings.append(_warning("portfolio_drawdown"))

    if risk_input.single_position_drawdown > limits.max_single_position_drawdown:
        warnings.append(_warning("single_position_drawdown"))

    if risk_input.st_warning:
        warnings.append(_warning("st_warning"))

    if risk_input.negative_event_count > 0:
        warnings.append(_warning("negative_event_count"))

    if risk_input.goodwill_ratio > limits.max_goodwill_ratio:
        warnings.append(_warning("goodwill_ratio"))

    if risk_input.pledge_ratio > limits.max_pledge_ratio:
        warnings.append(_warning("pledge_ratio"))

    if risk_input.main_outflow_days > limits.max_main_outflow_days:
        warnings.append(_warning("main_outflow_days"))

    if risk_input.index_below_annual_ma:
        warnings.append(_warning("index_below_annual_ma"))

    if risk_input.broad_market_drop_gt_3pct_count > limits.broad_market_drop_threshold:
        warnings.append(_warning("broad_market_drop_gt_3pct_count"))

    action = _strictest_action([warning.action for warning in warnings])
    return RiskEvaluation(action=action, warnings=warnings)


def _strictest_action(actions: list[RiskAction]) -> RiskAction:
    if not actions:
        return RiskAction.NONE
    return max(actions, key=lambda action: _ACTION_RANK[action])


def _warning(rule: str) -> RiskWarning:
    item = _RISK_RULES_BY_NAME[rule]
    return RiskWarning(
        layer=item.layer,
        rule=item.rule,
        action=item.action,
        message=item.message,
    )
