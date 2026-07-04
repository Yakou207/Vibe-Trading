from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.data import (  # noqa: E402
    AkShareProvider,
    AkShareRealtimeQuoteProvider,
    TushareProvider,
    load_universe_csv,
)
from fintech_quant.data.errors import MissingProviderCredential, MissingProviderDependency  # noqa: E402
from fintech_quant.information import AkShareFundamentalFetcher, TushareFundamentalFetcher  # noqa: E402


CHECK_CHOICES = (
    "akshare_daily",
    "akshare_realtime",
    "akshare_fundamental",
    "tushare_daily",
    "tushare_fundamental",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live smoke checks for configured A-share data sources.")
    parser.add_argument("--checks", default="akshare_daily,akshare_realtime,akshare_fundamental,tushare_daily,tushare_fundamental")
    parser.add_argument("--symbol", default="000001")
    parser.add_argument("--universe", default=None, help="Optional universe CSV; checks every symbol when provided.")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", default="outputs/data_source_health.json")
    parser.add_argument("--strict", action="store_true", help="Return non-zero if any check is failed or skipped.")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    checks = _parse_checks(args.checks)
    symbols = _symbols(args.symbol, args.universe)
    results = [_run_check(name, symbol, start, end) for symbol in symbols for name in checks]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbols[0],
        "symbols": symbols,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "checks": results,
        "summary": _summary(results),
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"source_health_path={output_path}")
    print(f"summary={payload['summary']}")
    if args.strict and (payload["summary"]["failed"] or payload["summary"]["skipped"]):
        return 1
    return 0


def _symbols(symbol: str, universe_path: str | None) -> list[str]:
    if universe_path:
        return [member.symbol for member in load_universe_csv(Path(universe_path))]
    from fintech_quant.data.symbols import normalize_a_share_symbol

    return [normalize_a_share_symbol(symbol)]


def _parse_checks(raw_checks: str) -> list[str]:
    checks = [item.strip() for item in raw_checks.split(",") if item.strip()]
    invalid = sorted(set(checks) - set(CHECK_CHOICES))
    if invalid:
        raise SystemExit(f"Unsupported checks: {', '.join(invalid)}")
    return checks


def _run_check(name: str, symbol: str, start: date, end: date) -> dict[str, object]:
    runners: dict[str, Callable[[str, date, date], list[dict[str, object]]]] = {
        "akshare_daily": _check_akshare_daily,
        "akshare_realtime": _check_akshare_realtime,
        "akshare_fundamental": _check_akshare_fundamental,
        "tushare_daily": _check_tushare_daily,
        "tushare_fundamental": _check_tushare_fundamental,
    }
    try:
        rows = runners[name](symbol, start, end)
    except MissingProviderCredential as exc:
        return _result(name, symbol, "skipped", 0, (), str(exc))
    except MissingProviderDependency as exc:
        return _result(name, symbol, "failed", 0, (), str(exc))
    except Exception as exc:
        return _result(name, symbol, "failed", 0, (), str(exc))
    return _result(name, symbol, "ok", len(rows), _fields(rows), "ok")


def _check_akshare_daily(symbol: str, start: date, end: date) -> list[dict[str, object]]:
    return AkShareProvider().history(symbol, start, end)


def _check_akshare_realtime(symbol: str, start: date, end: date) -> list[dict[str, object]]:
    del start, end
    return AkShareRealtimeQuoteProvider().quotes([symbol])


def _check_akshare_fundamental(symbol: str, start: date, end: date) -> list[dict[str, object]]:
    records = AkShareFundamentalFetcher().fetch(symbol, None, start, end)
    return [_record_row(record) for record in records]


def _check_tushare_daily(symbol: str, start: date, end: date) -> list[dict[str, object]]:
    return TushareProvider().history(symbol, start, end)


def _check_tushare_fundamental(symbol: str, start: date, end: date) -> list[dict[str, object]]:
    records = TushareFundamentalFetcher().fetch(symbol, None, start, end)
    return [_record_row(record) for record in records]


def _record_row(record: object) -> dict[str, object]:
    return {
        "symbol": getattr(record, "normalized_symbol", None),
        "published_at": getattr(record, "published_at", None).isoformat(),
        "source": getattr(record, "source", ""),
        "category": getattr(getattr(record, "category", None), "value", ""),
        "risk_tags": list(getattr(record, "risk_tags", ())),
    }


def _fields(rows: list[dict[str, object]]) -> tuple[str, ...]:
    fields: set[str] = set()
    for row in rows:
        fields.update(row)
    return tuple(sorted(fields))


def _result(
    name: str,
    symbol: str,
    status: str,
    row_count: int,
    fields: tuple[str, ...],
    message: str,
) -> dict[str, object]:
    return {
        "name": name,
        "symbol": symbol,
        "status": status,
        "row_count": row_count,
        "fields": list(fields),
        "message": message,
    }


def _summary(results: list[dict[str, object]]) -> dict[str, int]:
    return {
        "ok": sum(1 for result in results if result["status"] == "ok"),
        "failed": sum(1 for result in results if result["status"] == "failed"),
        "skipped": sum(1 for result in results if result["status"] == "skipped"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
