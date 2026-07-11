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
    "DrawdownPoint",
    "DrawdownResult",
    "EquityPoint",
    "PortfolioBacktestResult",
    "PortfolioBacktestTrade",
    "PortfolioDailyEquity",
    "PortfolioDatedRiskWarning",
    "ResearchBacktestResult",
    "TradeCost",
    "calculate_drawdown",
    "load_corporate_actions_csv",
    "run_portfolio_scored_baseline_backtest",
    "run_scored_baseline_backtest",
]
