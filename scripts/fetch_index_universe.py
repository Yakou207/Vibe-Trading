from __future__ import annotations

import argparse
import csv
import importlib
import sys
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.data.errors import MissingProviderDependency, ProviderFetchError  # noqa: E402
from fintech_quant.data.symbols import normalize_a_share_symbol  # noqa: E402


OUTPUT_FIELDS = ("symbol", "name", "sector", "index_code", "index_name", "weight", "as_of")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch CSI index constituents into a research universe CSV.")
    parser.add_argument("--source", choices=("akshare", "csv"), default="akshare")
    parser.add_argument("--input", default=None, help="CSV constituent fixture when --source csv.")
    parser.add_argument("--index-code", default="000906", help="CSI index code, e.g. 000300 or 000906.")
    parser.add_argument("--output", default="data/processed/csi800_universe.csv")
    parser.add_argument("--max-members", type=int, default=None)
    args = parser.parse_args()

    rows = _load_rows(args.source, args.index_code, args.input)
    members = _normalize_members(rows, args.index_code)
    if args.max_members is not None:
        if args.max_members <= 0:
            raise SystemExit("--max-members must be positive")
        members = members[: args.max_members]
    _write_universe(Path(args.output), members)
    print(f"index_code={args.index_code}")
    print(f"member_count={len(members)}")
    print(f"output={args.output}")
    return 0


def _load_rows(source: str, index_code: str, input_path: str | None) -> list[dict[str, object]]:
    if source == "csv":
        if not input_path:
            raise SystemExit("--input is required when --source csv")
        with Path(input_path).open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    try:
        ak = importlib.import_module("akshare")
    except ImportError as exc:
        raise MissingProviderDependency("akshare is required for index universe fetches") from exc
    try:
        frame = ak.index_stock_cons_weight_csindex(symbol=index_code)
    except Exception:
        try:
            frame = ak.index_stock_cons_csindex(symbol=index_code)
        except Exception as exc:
            raise ProviderFetchError(f"akshare index constituent fetch failed for {index_code!r}") from exc
    return frame.to_dict(orient="records")


def _normalize_members(rows: list[Mapping[str, object]], index_code: str) -> list[dict[str, object]]:
    members: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in rows:
        code = _first_value(row, "成分券代码", "code", "symbol")
        exchange = _optional_text(row.get("交易所") or row.get("exchange"))
        symbol = _normalize_symbol(str(code), exchange)
        if symbol in seen:
            continue
        seen.add(symbol)
        members.append(
            {
                "symbol": symbol,
                "name": str(_first_value(row, "成分券名称", "name")),
                "sector": "",
                "index_code": str(row.get("指数代码") or index_code),
                "index_name": str(row.get("指数名称") or ""),
                "weight": _optional_text(row.get("权重") or row.get("weight")) or "",
                "as_of": str(row.get("日期") or row.get("date") or ""),
            }
        )
    return sorted(members, key=lambda item: item["symbol"])


def _normalize_symbol(code: str, exchange: str | None) -> str:
    normalized = code.strip()
    if normalized.lower().startswith(("sh", "sz")):
        normalized = normalized[2:]
    if "." in normalized:
        return normalize_a_share_symbol(normalized)
    if exchange and "上海" in exchange:
        return f"{normalized}.SH"
    if exchange and "深圳" in exchange:
        return f"{normalized}.SZ"
    return normalize_a_share_symbol(normalized)


def _write_universe(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _first_value(row: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    raise ValueError(f"missing required field; expected one of {', '.join(keys)}")


def _optional_text(value: object | None) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
