from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.data import load_universe_csv  # noqa: E402


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
            "akshare_multi",
            "jsonl",
        ),
        default="akshare_multi",
    )
    parser.add_argument("--information-input", default=None, help="JSONL input when --information-source jsonl.")
    parser.add_argument("--market-source", choices=("akshare", "csv"), default="akshare")
    parser.add_argument("--market-input", default=None, help="CSV input when --market-source csv.")
    parser.add_argument("--information-output", default="data/raw/information/information.jsonl")
    parser.add_argument("--document-root", default="data/raw/information/financial_reports")
    parser.add_argument("--daily-output", default="data/processed/akshare_research_daily.csv")
    parser.add_argument("--feature-output", default="data/processed/akshare_research_features.csv")
    parser.add_argument("--market-output", default="data/raw/market_state/sh000001_market_state.csv")
    parser.add_argument("--rl-output", default="data/processed/rl_state_dataset.jsonl")
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
        ]
    )
    step_count += 1

    print(f"pipeline_steps={step_count}")
    print(f"information_output={args.information_output}")
    print(f"feature_output={args.feature_output}")
    print(f"market_output={args.market_output}")
    print(f"rl_output={args.rl_output}")
    print(f"report_output_root={args.report_output_root}")
    return 0


def _validate_args(args: argparse.Namespace) -> None:
    if args.price_source == "json" and not args.price_input:
        raise SystemExit("--price-input is required when --price-source json")
    if args.information_source == "jsonl" and not args.information_input:
        raise SystemExit("--information-input is required when --information-source jsonl")
    if args.market_source == "csv" and not args.market_input:
        raise SystemExit("--market-input is required when --market-source csv")


def _run(command: list[str]) -> None:
    subprocess.run([sys.executable, *command], cwd=ROOT, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
