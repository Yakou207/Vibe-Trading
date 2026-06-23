"""Research reports, backtest summaries, and run cards."""

from fintech_quant.reports.performance import (
    PerformanceSummary,
    StrategyComparison,
    compare_strategy_reports,
    summarize_report,
    write_comparison_report,
)

__all__ = [
    "PerformanceSummary",
    "StrategyComparison",
    "compare_strategy_reports",
    "summarize_report",
    "write_comparison_report",
]
