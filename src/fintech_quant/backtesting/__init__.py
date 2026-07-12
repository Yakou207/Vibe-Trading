"""Backtesting engine, market constraints, and performance metrics."""

from fintech_quant.backtesting.constraints import AShareTradingConstraints
from fintech_quant.backtesting.costs import AShareCostModel, TradeCost
from fintech_quant.backtesting.corporate_actions import (
    AppliedCorporateAction,
    CorporateAction,
    load_corporate_actions_csv,
)
from fintech_quant.backtesting.drawdown import (
    DrawdownEpisode,
    DrawdownPoint,
    DrawdownResult,
    EquityPoint,
    calculate_drawdown,
)
from fintech_quant.backtesting.drawdown_control import (
    DrawdownControlDecision,
    DrawdownControlPolicy,
    DrawdownControlState,
    DrawdownRegime,
    DrawdownTransition,
    drawdown_exposure_multiplier,
    standard_drawdown_control_policy,
    drawdown_control_state_from_json,
    drawdown_control_state_to_json,
    update_drawdown_control,
)
from fintech_quant.backtesting.dividend_tax import (
    DividendTaxLot,
    IndividualAShareDividendTaxPolicy,
    accrue_cash_dividend,
    settle_dividend_tax,
)
from fintech_quant.backtesting.portfolio_research_runner import (
    PortfolioBacktestResult,
    PortfolioBacktestTrade,
    PortfolioDailyEquity,
    PortfolioDatedRiskWarning,
    run_portfolio_scored_baseline_backtest,
)
from fintech_quant.backtesting.research_runner import (
    BacktestTrade,
    DailyEquity,
    DatedRiskWarning,
    ResearchBacktestResult,
    run_scored_baseline_backtest,
)

__all__ = [
    "AShareCostModel",
    "AShareTradingConstraints",
    "AppliedCorporateAction",
    "BacktestTrade",
    "DailyEquity",
    "CorporateAction",
    "DatedRiskWarning",
    "DrawdownEpisode",
    "DrawdownControlDecision",
    "DrawdownControlPolicy",
    "DrawdownControlState",
    "DrawdownPoint",
    "DrawdownResult",
    "DrawdownRegime",
    "DrawdownTransition",
    "DividendTaxLot",
    "EquityPoint",
    "IndividualAShareDividendTaxPolicy",
    "PortfolioBacktestResult",
    "PortfolioBacktestTrade",
    "PortfolioDailyEquity",
    "PortfolioDatedRiskWarning",
    "ResearchBacktestResult",
    "TradeCost",
    "calculate_drawdown",
    "accrue_cash_dividend",
    "drawdown_exposure_multiplier",
    "drawdown_control_state_from_json",
    "drawdown_control_state_to_json",
    "load_corporate_actions_csv",
    "run_portfolio_scored_baseline_backtest",
    "run_scored_baseline_backtest",
    "settle_dividend_tax",
    "standard_drawdown_control_policy",
    "update_drawdown_control",
]
