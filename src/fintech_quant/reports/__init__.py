"""Research reports, backtest summaries, and run cards."""

from fintech_quant.reports.performance import (
    PerformanceSummary,
    StrategyComparison,
    compare_strategy_reports,
    summarize_report,
    write_comparison_report,
)
from fintech_quant.reports.factor_analysis import build_factor_analysis_report, write_factor_analysis_report
from fintech_quant.reports.scoring_coverage import build_scoring_coverage_report
from fintech_quant.reports.paper_validation import audit_paper_validation

__all__ = [
    "PerformanceSummary",
    "StrategyComparison",
    "audit_paper_validation",
    "build_factor_analysis_report",
    "build_scoring_coverage_report",
    "compare_strategy_reports",
    "summarize_report",
    "write_factor_analysis_report",
    "write_comparison_report",
]
