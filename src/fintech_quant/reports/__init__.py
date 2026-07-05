"""Research reports, backtest summaries, and run cards."""

from fintech_quant.reports.performance import (
    PerformanceSummary,
    StrategyComparison,
    compare_strategy_reports,
    summarize_report,
    write_comparison_report,
)
from fintech_quant.reports.factor_analysis import build_factor_analysis_report, write_factor_analysis_report

__all__ = [
    "PerformanceSummary",
    "StrategyComparison",
    "build_factor_analysis_report",
    "compare_strategy_reports",
    "summarize_report",
    "write_factor_analysis_report",
    "write_comparison_report",
]
