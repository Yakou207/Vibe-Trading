from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import fetch_information  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check information source health without writing repository records.")
    parser.add_argument("--sources", default="akshare_multi")
    parser.add_argument("--input", default=None)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--sector", default=None)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", default="outputs/information_source_health.json")
    parser.add_argument("--report-type", default="重大事项")
    parser.add_argument("--recent-page", type=int, default=1)
    parser.add_argument("--recent-pages", type=int, default=1)
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    source_rows = [
        _check_source(source.strip(), args, start, end)
        for source in args.sources.split(",")
        if source.strip()
    ]
    payload = {
        "symbol": args.symbol,
        "sector": args.sector,
        "start": args.start,
        "end": args.end,
        "sources": source_rows,
        "summary": {
            "total_sources": len(source_rows),
            "ok_sources": sum(1 for row in source_rows if row["status"] == "ok"),
            "error_sources": sum(1 for row in source_rows if row["status"] == "error"),
            "total_records": sum(int(row["record_count"]) for row in source_rows if row["status"] == "ok"),
        },
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"health_report={output_path}")
    print(f"ok_sources={payload['summary']['ok_sources']}")
    print(f"error_sources={payload['summary']['error_sources']}")
    return 0


def _check_source(source: str, args: argparse.Namespace, start: date, end: date) -> dict[str, object]:
    source_args = argparse.Namespace(
        source=source,
        input=args.input,
        report_type=args.report_type,
        recent_page=args.recent_page,
        recent_pages=args.recent_pages,
    )
    try:
        records = fetch_information._build_fetcher(source_args).fetch(args.symbol, args.sector, start, end)
    except Exception as exc:
        return {
            "source": source,
            "status": "error",
            "record_count": 0,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }
    return {
        "source": source,
        "status": "ok",
        "record_count": len(records),
        "categories": sorted({record.category.value for record in records}),
    }


if __name__ == "__main__":
    raise SystemExit(main())
