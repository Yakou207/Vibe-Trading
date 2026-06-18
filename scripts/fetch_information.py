from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from fintech_quant.information import InformationRepository, StaticInformationFetcher


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch and store A-share information records.")
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--sector", default=None)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", default="data/raw/information/information.jsonl")
    args = parser.parse_args()

    repository = InformationRepository(Path(args.output))
    fetcher = StaticInformationFetcher(records=[])
    records = fetcher.fetch(
        symbol=args.symbol,
        sector=args.sector,
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
    )
    added = sum(1 for record in records if repository.append(record))
    print(f"stored_records={added}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
