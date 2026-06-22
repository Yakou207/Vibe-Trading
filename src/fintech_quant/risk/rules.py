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
    max_position_weight: float = 0.1
    max_portfolio_drawdown: float = 0.15
    max_single_position_drawdown: float = 0.08
    max_goodwill_ratio: float = 0.30
    max_pledge_ratio: float = 0.50
    max_main_outflow_days: int = 3
    broad_market_drop_threshold: int = 15


@dataclass(frozen=True)
class RiskInput:
    portfolio_drawdown: float = 0.0
    single_position_drawdown: float = 0.0
    st_warning: bool = False
    goodwill_ratio: float = 0.0
    pledge_ratio: float = 0.0
    main_outflow_days: int = 0
    index_below_annual_ma: bool = False
    broad_market_drop_count: int = 0


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

    if risk_input.portfolio_drawdown >= limits.max_portfolio_drawdown:
        warnings.append(
            RiskWarning(
                layer="portfolio_drawdown",
                rule="portfolio_drawdown",
                action=RiskAction.LIQUIDATE,
                message="Portfolio drawdown reached liquidation threshold.",
            )
        )

    if risk_input.single_position_drawdown > limits.max_single_position_drawdown:
        warnings.append(
            RiskWarning(
                layer="single_stock_negative",
                rule="single_position_drawdown",
                action=RiskAction.REDUCE,
                message="Single position drawdown exceeded risk threshold.",
            )
        )

    if risk_input.st_warning:
        warnings.append(
            RiskWarning(
                layer="single_stock_negative",
                rule="st_warning",
                action=RiskAction.REDUCE,
                message="ST warning is active for the stock.",
            )
        )

    if risk_input.goodwill_ratio > limits.max_goodwill_ratio:
        warnings.append(
            RiskWarning(
                layer="single_stock_negative",
                rule="goodwill_ratio",
                action=RiskAction.WATCH,
                message="Goodwill ratio exceeded watch threshold.",
            )
        )

    if risk_input.pledge_ratio > limits.max_pledge_ratio:
        warnings.append(
            RiskWarning(
                layer="single_stock_negative",
                rule="pledge_ratio",
                action=RiskAction.WATCH,
                message="Share pledge ratio exceeded watch threshold.",
            )
        )

    if risk_input.main_outflow_days > limits.max_main_outflow_days:
        warnings.append(
            RiskWarning(
                layer="single_stock_negative",
                rule="main_outflow_days",
                action=RiskAction.WATCH,
                message="Main capital outflow continued beyond threshold.",
            )
        )

    if risk_input.index_below_annual_ma:
        warnings.append(
            RiskWarning(
                layer="broad_market_abnormal",
                rule="index_below_annual_ma",
                action=RiskAction.WATCH,
                message="Broad index is below the 250-day moving average.",
            )
        )

    if risk_input.broad_market_drop_count > limits.broad_market_drop_threshold:
        warnings.append(
            RiskWarning(
                layer="systemic_risk",
                rule="broad_market_drop_count",
                action=RiskAction.REDUCE,
                message="More than 15 tracked names fell over 3% in one day.",
            )
        )

    action = _strictest_action([warning.action for warning in warnings])
    return RiskEvaluation(action=action, warnings=warnings)


def _strictest_action(actions: list[RiskAction]) -> RiskAction:
    if not actions:
        return RiskAction.NONE
    return max(actions, key=lambda action: _ACTION_RANK[action])
