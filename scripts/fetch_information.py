from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.information import (
    AkShareDragonTigerFetcher,
    AkShareFundFlowFetcher,
    AkShareFundamentalFetcher,
    AkShareFinancialStatementFetcher,
    AkShareMarginFetcher,
    AkShareNoticeFetcher,
    AkSharePledgeRatioFetcher,
    AkSharePolicyNewsFetcher,
    AkShareStStatusFetcher,
    CombinedInformationFetcher,
    InformationRepository,
    JsonlInformationFetcher,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch and store A-share information records.")
    parser.add_argument(
        "--source",
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
        default="akshare_notice",
    )
    parser.add_argument("--input", default=None)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--sector", default=None)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", default="data/raw/information/information.jsonl")
    parser.add_argument("--report-type", default="重大事项")
    parser.add_argument(
        "--retention-as-of",
        default=None,
        help="Override the retention cutoff date for text records (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--recent-page",
        type=int,
        default=1,
        help="First AkShare notice page to fetch.",
    )
    parser.add_argument(
        "--recent-pages",
        type=int,
        default=1,
        help="Number of AkShare notice pages to fetch from --recent-page.",
    )
    args = parser.parse_args()

    repository = InformationRepository(Path(args.output))
    fetcher = _build_fetcher(args)
    records = fetcher.fetch(args.symbol, args.sector, date.fromisoformat(args.start), date.fromisoformat(args.end))
    added = sum(1 for record in records if repository.append(record))
    retention_as_of = date.fromisoformat(args.retention_as_of) if args.retention_as_of else date.today()
    pruned = repository.prune_text_records(retention_as_of)
    print(f"stored_records={added}")
    print(f"pruned_text_records={pruned}")
    return 0


def _build_fetcher(args: argparse.Namespace):
    if args.source == "jsonl":
        if not args.input:
            raise SystemExit("--input is required when --source jsonl")
        return JsonlInformationFetcher(Path(args.input))
    if args.source == "akshare_multi":
        return CombinedInformationFetcher(
            [
                AkShareNoticeFetcher(
                    report_type=args.report_type,
                    recent_page=args.recent_page,
                    recent_pages=args.recent_pages,
                ),
                AkShareNoticeFetcher(
                    report_type="财务报告",
                    recent_page=args.recent_page,
                    recent_pages=args.recent_pages,
                ),
                AkSharePolicyNewsFetcher(),
                AkShareFundamentalFetcher(),
                AkShareFinancialStatementFetcher(),
                AkSharePledgeRatioFetcher(),
                AkShareStStatusFetcher(),
                AkShareFundFlowFetcher(),
                AkShareMarginFetcher(),
                AkShareDragonTigerFetcher(),
            ],
            ignore_fetch_errors=True,
        )
    if args.source == "akshare_financial_report":
        return AkShareNoticeFetcher(
            report_type="财务报告",
            recent_page=args.recent_page,
            recent_pages=args.recent_pages,
        )
    if args.source == "akshare_policy":
        return AkSharePolicyNewsFetcher()
    if args.source == "akshare_fundamental":
        return AkShareFundamentalFetcher()
    if args.source == "akshare_financial_statement":
        return AkShareFinancialStatementFetcher()
    if args.source == "akshare_pledge_ratio":
        return AkSharePledgeRatioFetcher()
    if args.source == "akshare_st_status":
        return AkShareStStatusFetcher()
    return AkShareNoticeFetcher(
        report_type=args.report_type,
        recent_page=args.recent_page,
        recent_pages=args.recent_pages,
    )


if __name__ == "__main__":
    raise SystemExit(main())
