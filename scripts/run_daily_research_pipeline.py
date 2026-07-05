from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.data import UniverseMember, load_universe_csv  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the daily A-share research data pipeline.")
    parser.add_argument("--universe", required=True, help="CSV with selected A-share symbols.")
    parser.add_argument("--start", required=True, help="Pipeline start date, YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="Pipeline end date, YYYY-MM-DD.")
    parser.add_argument("--price-source", choices=("json", "auto", "akshare", "tushare"), default="akshare")
    parser.add_argument("--price-input", default=None, help="JSON daily-bar input when --price-source json.")
    parser.add_argument(
        "--information-source",
        choices=(
            "akshare_notice",
            "akshare_financial_report",
            "akshare_policy",
            "akshare_fundamental",
            "akshare_financial_statement",
            "akshare_pledge_ratio",
            "akshare_st_status",
            "tushare_fundamental",
            "akshare_multi",
            "jsonl",
        ),
        default="akshare_multi",
    )
    parser.add_argument("--information-input", default=None, help="JSONL input when --information-source jsonl.")
    parser.add_argument("--market-source", choices=("akshare", "csv"), default="akshare")
    parser.add_argument("--market-input", default=None, help="CSV input when --market-source csv.")
    parser.add_argument("--information-output", default="data/raw/information/information.jsonl")
    parser.add_argument("--classified-information-output-dir", default="data/raw/information/classified")
    parser.add_argument("--information-summary-output", default="outputs/information_repository_summary.json")
    parser.add_argument("--information-summary-recent-days", type=int, default=30)
    parser.add_argument("--document-root", default="data/raw/information/financial_reports")
    parser.add_argument("--daily-output", default="data/processed/akshare_research_daily.csv")
    parser.add_argument("--feature-output", default="data/processed/akshare_research_features.csv")
    parser.add_argument("--market-output", default="data/raw/market_state/sh000001_market_state.csv")
    parser.add_argument("--rl-output", default="data/processed/rl_state_dataset.jsonl")
    parser.add_argument("--rl-policy-report-output", default=None)
    parser.add_argument("--rl-policy", choices=("always_hold", "buy_and_hold"), default="buy_and_hold")
    parser.add_argument("--rl-policy-symbol", default=None)
    parser.add_argument("--rl-policy-transaction-cost", type=float, default=0.0)
    parser.add_argument("--dqn-policy-report-output", default=None)
    parser.add_argument("--dqn-policy-symbol", default=None)
    parser.add_argument("--dqn-epochs", type=int, default=50)
    parser.add_argument("--dqn-learning-rate", type=float, default=0.05)
    parser.add_argument("--dqn-gamma", type=float, default=0.0)
    parser.add_argument("--dqn-policy-transaction-cost", type=float, default=0.0)
    parser.add_argument("--dqn-eval-start", default=None)
    parser.add_argument("--strategy-comparison-output", default=None)
    parser.add_argument("--strategy-comparison-align-to-candidate", action="store_true")
    parser.add_argument("--scoring-coverage-output", default="outputs/scoring_coverage.json")
    parser.add_argument("--stock-analysis-output", default=None)
    parser.add_argument("--buy-threshold", type=float, default=70.0)
    parser.add_argument("--min-score-confidence", type=float, default=0.8)
    parser.add_argument("--max-portfolio-drawdown", type=float, default=0.15)
    parser.add_argument("--max-single-position-drawdown", type=float, default=0.08)
    parser.add_argument("--max-goodwill-ratio", type=float, default=0.30)
    parser.add_argument("--max-pledge-ratio", type=float, default=0.50)
    parser.add_argument("--max-main-outflow-days", type=int, default=3)
    parser.add_argument("--broad-market-drop-threshold", type=int, default=15)
    parser.add_argument("--preflight-data-sources", action="store_true")
    parser.add_argument(
        "--preflight-data-source-checks",
        default="akshare_daily,akshare_realtime,akshare_fundamental,tushare_daily,tushare_fundamental",
    )
    parser.add_argument("--data-source-health-output", default="outputs/data_source_health.json")
    parser.add_argument("--preflight-data-source-strict", action="store_true")
    parser.add_argument("--run-id", default="daily-pipeline-baseline")
    parser.add_argument("--report-output-root", default="outputs/research_runs")
    parser.add_argument("--index-symbol", default="sh000001")
    parser.add_argument("--ma-window", type=int, default=250)
    parser.add_argument("--report-type", default="重大事项")
    parser.add_argument("--recent-page", type=int, default=1)
    parser.add_argument("--recent-pages", type=int, default=1)
    args = parser.parse_args()

    _validate_args(args)
    universe = load_universe_csv(Path(args.universe))

    step_count = 0
    if args.preflight_data_sources:
        preflight_command = [
            "scripts/check_data_sources.py",
            "--checks",
            args.preflight_data_source_checks,
            "--universe",
            args.universe,
            "--start",
            args.start,
            "--end",
            args.end,
            "--output",
            args.data_source_health_output,
        ]
        if args.preflight_data_source_strict:
            preflight_command.append("--strict")
        _run(preflight_command)
        step_count += 1

    for member in universe:
        command = [
            "scripts/fetch_information.py",
            "--source",
            args.information_source,
            "--symbol",
            member.symbol,
            "--start",
            args.start,
            "--end",
            args.end,
            "--output",
            args.information_output,
            "--report-type",
            args.report_type,
            "--recent-page",
            str(args.recent_page),
            "--recent-pages",
            str(args.recent_pages),
        ]
        if args.information_input:
            command.extend(["--input", args.information_input])
        _run(command)
    for sector in _universe_sectors(universe):
        command = [
            "scripts/fetch_information.py",
            "--source",
            args.information_source,
            "--sector",
            sector,
            "--start",
            args.start,
            "--end",
            args.end,
            "--output",
            args.information_output,
            "--report-type",
            args.report_type,
            "--recent-page",
            str(args.recent_page),
            "--recent-pages",
            str(args.recent_pages),
        ]
        if args.information_input:
            command.extend(["--input", args.information_input])
        _run(command)
    step_count += 1

    _run(
        [
            "scripts/archive_financial_reports.py",
            "--input",
            args.information_output,
            "--document-root",
            args.document_root,
        ]
    )
    step_count += 1

    _run(["scripts/analyze_information_sentiment.py", "--input", args.information_output])
    step_count += 1

    _run(
        [
            "scripts/export_information_repository.py",
            "--input",
            args.information_output,
            "--output-dir",
            args.classified_information_output_dir,
        ]
    )
    step_count += 1

    _run(
        [
            "scripts/summarize_information_repository.py",
            "--input",
            args.information_output,
            "--as-of",
            args.end,
            "--recent-days",
            str(args.information_summary_recent_days),
            "--output",
            args.information_summary_output,
        ]
    )
    step_count += 1

    price_command = [
        "scripts/refresh_research_data.py",
        "--source",
        args.price_source,
        "--universe",
        args.universe,
        "--daily-output",
        args.daily_output,
        "--feature-output",
        args.feature_output,
    ]
    if args.price_input:
        price_command.extend(["--input", args.price_input])
    if args.price_source != "json":
        price_command.extend(["--start", args.start, "--end", args.end])
    _run(price_command)
    step_count += 1

    market_command = [
        "scripts/fetch_market_state.py",
        "--source",
        args.market_source,
        "--index-symbol",
        args.index_symbol,
        "--start",
        args.start,
        "--end",
        args.end,
        "--output",
        args.market_output,
        "--ma-window",
        str(args.ma_window),
    ]
    if args.market_input:
        market_command.extend(["--input", args.market_input])
    _run(market_command)
    step_count += 1

    _run(
        [
            "scripts/build_rl_dataset.py",
            "--features",
            args.feature_output,
            "--universe",
            args.universe,
            "--information",
            args.information_output,
            "--market-state",
            args.market_output,
            "--output",
            args.rl_output,
        ]
    )
    step_count += 1

    if args.rl_policy_report_output:
        rl_policy_command = [
            "scripts/evaluate_rl_policy.py",
            "--input",
            args.rl_output,
            "--output",
            args.rl_policy_report_output,
            "--policy",
            args.rl_policy,
            "--transaction-cost",
            str(args.rl_policy_transaction_cost),
            "--run-id",
            f"{args.run_id}-{args.rl_policy}",
        ]
        if args.rl_policy_symbol:
            rl_policy_command.extend(["--symbol", args.rl_policy_symbol])
        _run(rl_policy_command)
        step_count += 1

    if args.dqn_policy_report_output:
        dqn_policy_command = [
            "scripts/train_dqn_policy.py",
            "--input",
            args.rl_output,
            "--output",
            args.dqn_policy_report_output,
            "--epochs",
            str(args.dqn_epochs),
            "--learning-rate",
            str(args.dqn_learning_rate),
            "--gamma",
            str(args.dqn_gamma),
            "--transaction-cost",
            str(args.dqn_policy_transaction_cost),
            "--run-id",
            f"{args.run_id}-linear-q-dqn",
        ]
        if args.dqn_policy_symbol:
            dqn_policy_command.extend(["--symbol", args.dqn_policy_symbol])
        if args.dqn_eval_start:
            dqn_policy_command.extend(["--eval-start", args.dqn_eval_start])
        _run(dqn_policy_command)
        step_count += 1

    _run(
        [
            "scripts/summarize_scoring_coverage.py",
            "--features",
            args.feature_output,
            "--universe",
            args.universe,
            "--information",
            args.information_output,
            "--market-state",
            args.market_output,
            "--output",
            args.scoring_coverage_output,
        ]
    )
    step_count += 1

    if args.stock_analysis_output:
        _run(
            [
                "scripts/analyze_stock_scores.py",
                "--features",
                args.feature_output,
                "--universe",
                args.universe,
                "--information",
                args.information_output,
                "--market-state",
                args.market_output,
                "--output",
                args.stock_analysis_output,
            ]
        )
        step_count += 1

    _run(
        [
            "scripts/run_research_baseline.py",
            "--run-id",
            args.run_id,
            "--features",
            args.feature_output,
            "--universe",
            args.universe,
            "--information",
            args.information_output,
            "--market-state",
            args.market_output,
            "--output-root",
            args.report_output_root,
            "--buy-threshold",
            str(args.buy_threshold),
            "--min-score-confidence",
            str(args.min_score_confidence),
            "--max-portfolio-drawdown",
            str(args.max_portfolio_drawdown),
            "--max-single-position-drawdown",
            str(args.max_single_position_drawdown),
            "--max-goodwill-ratio",
            str(args.max_goodwill_ratio),
            "--max-pledge-ratio",
            str(args.max_pledge_ratio),
            "--max-main-outflow-days",
            str(args.max_main_outflow_days),
            "--broad-market-drop-threshold",
            str(args.broad_market_drop_threshold),
        ]
    )
    step_count += 1

    if args.strategy_comparison_output:
        baseline_report = Path(args.report_output_root) / args.run_id / "run_report.json"
        comparison_command = [
            "scripts/compare_strategy_reports.py",
            "--baseline",
            str(baseline_report),
            "--candidate",
            args.dqn_policy_report_output,
            "--output",
            args.strategy_comparison_output,
        ]
        if args.strategy_comparison_align_to_candidate:
            comparison_command.append("--align-to-candidate")
        _run(comparison_command)
        step_count += 1

    print(f"pipeline_steps={step_count}")
    print(f"information_output={args.information_output}")
    print(f"classified_information_output_dir={args.classified_information_output_dir}")
    print(f"information_summary_output={args.information_summary_output}")
    print(f"feature_output={args.feature_output}")
    print(f"market_output={args.market_output}")
    print(f"rl_output={args.rl_output}")
    if args.rl_policy_report_output:
        print(f"rl_policy_report_output={args.rl_policy_report_output}")
    if args.dqn_policy_report_output:
        print(f"dqn_policy_report_output={args.dqn_policy_report_output}")
    if args.dqn_eval_start:
        print(f"dqn_eval_start={args.dqn_eval_start}")
    if args.strategy_comparison_output:
        print(f"strategy_comparison_output={args.strategy_comparison_output}")
    print(f"scoring_coverage_output={args.scoring_coverage_output}")
    if args.stock_analysis_output:
        print(f"stock_analysis_output={args.stock_analysis_output}")
    if args.preflight_data_sources:
        print(f"data_source_health_output={args.data_source_health_output}")
    print(f"report_output_root={args.report_output_root}")
    return 0


def _validate_args(args: argparse.Namespace) -> None:
    if args.price_source == "json" and not args.price_input:
        raise SystemExit("--price-input is required when --price-source json")
    if args.information_source == "jsonl" and not args.information_input:
        raise SystemExit("--information-input is required when --information-source jsonl")
    if args.market_source == "csv" and not args.market_input:
        raise SystemExit("--market-input is required when --market-source csv")
    if args.strategy_comparison_output and not args.dqn_policy_report_output:
        raise SystemExit("--dqn-policy-report-output is required when --strategy-comparison-output is set")


def _universe_sectors(universe: Sequence[UniverseMember]) -> list[str]:
    return sorted({member.sector for member in universe if member.sector})


def _run(command: list[str]) -> None:
    subprocess.run([sys.executable, *command], cwd=ROOT, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
