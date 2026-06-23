"""Backtesting engine, market constraints, and performance metrics."""

from fintech_quant.backtesting.drawdown import (
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
    "BacktestTrade",
    "DailyEquity",
    "DatedRiskWarning",
    "DrawdownPoint",
    "DrawdownResult",
    "EquityPoint",
    "PortfolioBacktestResult",
    "PortfolioBacktestTrade",
    "PortfolioDailyEquity",
    "PortfolioDatedRiskWarning",
    "ResearchBacktestResult",
    "calculate_drawdown",
    "run_portfolio_scored_baseline_backtest",
    "run_scored_baseline_backtest",
]
