from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.information import AkShareNoticeFetcher, InformationRepository, JsonlInformationFetcher


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch and store A-share information records.")
    parser.add_argument("--source", choices=("akshare_notice", "jsonl"), default="akshare_notice")
    parser.add_argument("--input", default=None)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--sector", default=None)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", default="data/raw/information/information.jsonl")
    parser.add_argument("--report-type", default="重大事项")
    parser.add_argument(
        "--recent-page",
        type=int,
        default=1,
        help="AkShare notice page to fetch. Date filtering is page-bounded to this page.",
    )
    args = parser.parse_args()

    repository = InformationRepository(Path(args.output))
    fetcher = _build_fetcher(args)
    records = fetcher.fetch(args.symbol, args.sector, date.fromisoformat(args.start), date.fromisoformat(args.end))
    added = sum(1 for record in records if repository.append(record))
    print(f"stored_records={added}")
    return 0


def _build_fetcher(args: argparse.Namespace):
    if args.source == "jsonl":
        if not args.input:
            raise SystemExit("--input is required when --source jsonl")
        return JsonlInformationFetcher(Path(args.input))
    return AkShareNoticeFetcher(report_type=args.report_type, recent_page=args.recent_page)


if __name__ == "__main__":
    raise SystemExit(main())
