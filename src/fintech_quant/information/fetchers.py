from __future__ import annotations

import importlib
import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

from fintech_quant.data.errors import MissingProviderDependency, ProviderFetchError
from fintech_quant.data.symbols import normalize_a_share_symbol
from fintech_quant.information.models import InformationCategory, InformationRecord


class InformationFetcher(ABC):
    @abstractmethod
    def fetch(
        self,
        symbol: str | None,
        sector: str | None,
        start: date,
        end: date,
    ) -> list[InformationRecord]:
        """Return source-backed information records for the requested scope."""


class StaticInformationFetcher(InformationFetcher):
    def __init__(self, records: list[InformationRecord]) -> None:
        self._records = records

    def fetch(
        self,
        symbol: str | None,
        sector: str | None,
        start: date,
        end: date,
    ) -> list[InformationRecord]:
        return _filter_records(self._records, symbol, sector, start, end)


class JsonlInformationFetcher(InformationFetcher):
    def __init__(self, path: Path) -> None:
        self._path = path

    def fetch(
        self,
        symbol: str | None,
        sector: str | None,
        start: date,
        end: date,
    ) -> list[InformationRecord]:
        if not self._path.exists():
            return []

        records: list[InformationRecord] = []
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    records.append(_record_from_json(json.loads(line)))
        return _filter_records(records, symbol, sector, start, end)


class CombinedInformationFetcher(InformationFetcher):
    def __init__(self, fetchers: list[InformationFetcher]) -> None:
        self._fetchers = fetchers

    def fetch(
        self,
        symbol: str | None,
        sector: str | None,
        start: date,
        end: date,
    ) -> list[InformationRecord]:
        records: list[InformationRecord] = []
        for fetcher in self._fetchers:
            records.extend(fetcher.fetch(symbol, sector, start, end))
        return sorted(records, key=lambda record: (record.published_at, record.normalized_symbol or "", record.title))


class AkShareNoticeFetcher(InformationFetcher):
    """Fetch AkShare notice rows from one recent page and filter them locally by date."""

    def __init__(
        self,
        report_type: str = "重大事项",
        recent_page: int = 1,
        fetcher: Callable[[], object] | None = None,
    ) -> None:
        self._report_type = report_type
        self._recent_page = recent_page
        self._fetcher = fetcher

    def fetch(
        self,
        symbol: str | None,
        sector: str | None,
        start: date,
        end: date,
    ) -> list[InformationRecord]:
        rows = self._fetch_rows()
        try:
            records = [_record_from_notice_row(row, self._report_type) for row in rows]
        except Exception as exc:
            raise ProviderFetchError(
                f"akshare notice fetch failed for report_type={self._report_type!r}, recent_page={self._recent_page!r}"
            ) from exc
        return _filter_records(records, symbol, sector, start, end)

    def _fetch_rows(self) -> list[dict[str, object]]:
        if self._fetcher is not None:
            return self._run_fetch(self._fetcher)

        try:
            ak = importlib.import_module("akshare")
        except ImportError as exc:
            raise MissingProviderDependency("akshare is required for AkShareNoticeFetcher") from exc

        return self._run_fetch(
            lambda: ak.stock_notice_report(
                report_type=self._report_type,
                recent_page=self._recent_page,
            ).to_dict(orient="records")
        )

    def _run_fetch(self, fetcher: Callable[[], object]) -> list[dict[str, object]]:
        try:
            return list(fetcher())
        except Exception as exc:
            raise ProviderFetchError(
                f"akshare notice fetch failed for report_type={self._report_type!r}, recent_page={self._recent_page!r}"
            ) from exc


class AkShareFundFlowFetcher(InformationFetcher):
    def __init__(self, fetcher: Callable[[str, str], object] | None = None) -> None:
        self._fetcher = fetcher

    def fetch(
        self,
        symbol: str | None,
        sector: str | None,
        start: date,
        end: date,
    ) -> list[InformationRecord]:
        del sector
        if symbol is None:
            return []
        normalized_symbol = normalize_a_share_symbol(symbol)
        market = _market_from_symbol(normalized_symbol)
        plain_symbol = _plain_symbol(normalized_symbol)
        try:
            rows = self._fetch_rows(plain_symbol, market)
            records = [_record_from_fund_flow_row(row, normalized_symbol) for row in rows]
        except Exception as exc:
            raise ProviderFetchError(f"akshare fund-flow fetch failed for symbol={normalized_symbol!r}") from exc
        return _filter_records(records, normalized_symbol, None, start, end)

    def _fetch_rows(self, symbol: str, market: str) -> list[dict[str, object]]:
        if self._fetcher is not None:
            return _rows_from_fetch_result(self._fetcher(symbol, market))
        try:
            ak = importlib.import_module("akshare")
        except ImportError as exc:
            raise MissingProviderDependency("akshare is required for AkShareFundFlowFetcher") from exc
        return _rows_from_fetch_result(ak.stock_individual_fund_flow(stock=symbol, market=market))


class AkShareMarginFetcher(InformationFetcher):
    def __init__(self, fetcher: Callable[[date, str], object] | None = None) -> None:
        self._fetcher = fetcher

    def fetch(
        self,
        symbol: str | None,
        sector: str | None,
        start: date,
        end: date,
    ) -> list[InformationRecord]:
        del sector
        if symbol is None:
            return []
        normalized_symbol = normalize_a_share_symbol(symbol)
        market = _market_from_symbol(normalized_symbol)
        records: list[InformationRecord] = []
        try:
            for trade_date in _date_range(start, end):
                rows = self._fetch_rows(trade_date, market)
                records.extend(_record_from_margin_row(row, normalized_symbol, trade_date) for row in rows)
        except Exception as exc:
            raise ProviderFetchError(f"akshare margin fetch failed for symbol={normalized_symbol!r}") from exc
        return _filter_records(records, normalized_symbol, None, start, end)

    def _fetch_rows(self, trade_date: date, market: str) -> list[dict[str, object]]:
        if self._fetcher is not None:
            return _rows_from_fetch_result(self._fetcher(trade_date, market))
        try:
            ak = importlib.import_module("akshare")
        except ImportError as exc:
            raise MissingProviderDependency("akshare is required for AkShareMarginFetcher") from exc
        function_name = "stock_margin_detail_sse" if market == "sh" else "stock_margin_detail_szse"
        function = getattr(ak, function_name)
        return _rows_from_fetch_result(function(date=trade_date.strftime("%Y%m%d")))


class AkShareDragonTigerFetcher(InformationFetcher):
    def __init__(
        self,
        window: str = "5",
        *,
        as_of: date | None = None,
        fetcher: Callable[[str], object] | None = None,
    ) -> None:
        self._window = window
        self._as_of = as_of
        self._fetcher = fetcher

    def fetch(
        self,
        symbol: str | None,
        sector: str | None,
        start: date,
        end: date,
    ) -> list[InformationRecord]:
        del sector
        as_of = self._as_of or date.today()
        if not start <= as_of <= end:
            return []
        try:
            records = [_record_from_dragon_tiger_row(row, as_of) for row in self._fetch_rows()]
        except Exception as exc:
            raise ProviderFetchError(f"akshare dragon-tiger fetch failed for window={self._window!r}") from exc
        return _filter_records(records, symbol, None, start, end)

    def _fetch_rows(self) -> list[dict[str, object]]:
        if self._fetcher is not None:
            return _rows_from_fetch_result(self._fetcher(self._window))
        try:
            ak = importlib.import_module("akshare")
        except ImportError as exc:
            raise MissingProviderDependency("akshare is required for AkShareDragonTigerFetcher") from exc
        return _rows_from_fetch_result(ak.stock_lhb_ggtj_sina(symbol=self._window))


def _filter_records(
    records: list[InformationRecord],
    symbol: str | None,
    sector: str | None,
    start: date,
    end: date,
) -> list[InformationRecord]:
    normalized_symbol = normalize_a_share_symbol(symbol) if symbol else None
    return [
        record
        for record in records
        if start <= record.published_at <= end
        and (normalized_symbol is None or record.normalized_symbol == normalized_symbol)
        and (sector is None or record.sector == sector)
    ]


def _record_from_json(data: dict[str, object]) -> InformationRecord:
    return InformationRecord(
        symbol=data.get("symbol") if isinstance(data.get("symbol"), str) else None,
        sector=data.get("sector") if isinstance(data.get("sector"), str) else None,
        published_at=_parse_date(data["published_at"]),
        source=str(data["source"]),
        category=InformationCategory(str(data["category"])),
        title=str(data["title"]),
        url=str(data.get("url", "")),
        summary=str(data.get("summary", "")),
        risk_tags=tuple(str(tag) for tag in data.get("risk_tags", ())),
    )


def _record_from_notice_row(row: dict[str, object], report_type: str) -> InformationRecord:
    category = InformationCategory.FINANCIAL_REPORT if report_type == "财务报告" else InformationCategory.COMPANY_ANNOUNCEMENT
    risk_tags = ("negative_announcement",) if report_type == "风险提示" else ()
    return InformationRecord(
        symbol=str(row["代码"]).strip().zfill(6),
        sector=None,
        published_at=_parse_date(row["公告日期"]),
        source="akshare_notice",
        category=category,
        title=str(row["公告标题"]).strip(),
        url=str(_first_notice_url(row)),
        summary=str(row.get("公告类型", "")).strip(),
        risk_tags=risk_tags,
    )


def _record_from_fund_flow_row(row: dict[str, object], normalized_symbol: str) -> InformationRecord:
    trade_date = _parse_date(_first_value(row, "日期", "trade_date", "date"))
    main_net_inflow = _float_value(_first_value(row, "主力净流入", "主力净流入-净额", "main_net_inflow", default=0.0))
    tags = ["selected_universe", "capital_flow"]
    tags.append("main_inflow" if main_net_inflow > 0 else "main_outflow")
    return InformationRecord(
        symbol=normalized_symbol,
        sector=None,
        published_at=trade_date,
        source="akshare_fund_flow",
        category=InformationCategory.STOCK_DATA,
        title=f"{normalized_symbol} fund flow",
        url="",
        summary=f"main_net_inflow={main_net_inflow}",
        risk_tags=tuple(tags),
    )


def _record_from_margin_row(row: dict[str, object], normalized_symbol: str, fallback_date: date) -> InformationRecord:
    row_symbol = _first_value(row, "标的证券代码", "证券代码", "代码", "symbol", default=_plain_symbol(normalized_symbol))
    row_normalized = normalize_a_share_symbol(str(row_symbol).strip())
    trade_date = _parse_date(_first_value(row, "信用交易日期", "交易日期", "日期", "trade_date", default=fallback_date))
    financing_balance = _float_value(_first_value(row, "融资余额", "financing_balance", default=0.0))
    short_balance = _float_value(_first_value(row, "融券余量", "融券余额", "short_balance", default=0.0))
    return InformationRecord(
        symbol=row_normalized,
        sector=None,
        published_at=trade_date,
        source="akshare_margin",
        category=InformationCategory.STOCK_DATA,
        title=f"{row_normalized} margin financing",
        url="",
        summary=f"financing_balance={financing_balance}; short_balance={short_balance}",
        risk_tags=("selected_universe", "margin_financing"),
    )


def _record_from_dragon_tiger_row(row: dict[str, object], published_at: date) -> InformationRecord:
    raw_symbol = _first_value(row, "代码", "股票代码", "symbol")
    normalized_symbol = normalize_a_share_symbol(str(raw_symbol).strip())
    net_amount = _float_value(_first_value(row, "净额", "净买额", "净买入额", "net_amount", default=0.0))
    listed_count = _first_value(row, "上榜次数", "listed_count", default="")
    tags = ["dragon_tiger"]
    tags.append("dragon_tiger_positive" if net_amount >= 0 else "dragon_tiger_negative")
    return InformationRecord(
        symbol=normalized_symbol,
        sector=None,
        published_at=published_at,
        source="akshare_dragon_tiger",
        category=InformationCategory.MARKET_SENTIMENT,
        title=f"{normalized_symbol} dragon tiger",
        url="",
        summary=f"listed_count={listed_count}; net_amount={net_amount}",
        risk_tags=tuple(tags),
    )


def _first_notice_url(row: dict[str, object]) -> str:
    for key in ("公告链接", "网址", "url"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _rows_from_fetch_result(result: object) -> list[dict[str, object]]:
    if hasattr(result, "to_dict"):
        return list(result.to_dict(orient="records"))
    return [dict(row) for row in result]  # type: ignore[arg-type]


def _first_value(row: dict[str, object], *keys: str, default: object | None = None) -> object:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    if default is not None:
        return default
    raise KeyError(keys[0])


def _market_from_symbol(normalized_symbol: str) -> str:
    if normalized_symbol.endswith(".SH"):
        return "sh"
    if normalized_symbol.endswith(".SZ"):
        return "sz"
    if normalized_symbol.endswith(".BJ"):
        return "bj"
    raise ValueError(f"unsupported A-share symbol: {normalized_symbol}")


def _plain_symbol(normalized_symbol: str) -> str:
    return normalized_symbol.split(".", 1)[0]


def _date_range(start: date, end: date) -> list[date]:
    if end < start:
        return []
    days = (end - start).days
    return [start + timedelta(days=offset) for offset in range(days + 1)]


def _float_value(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text.endswith("%"):
        text = text[:-1]
    unit_multiplier = 1.0
    if text.endswith("万"):
        unit_multiplier = 10000.0
        text = text[:-1]
    elif text.endswith("亿"):
        unit_multiplier = 100000000.0
        text = text[:-1]
    return float(text) * unit_multiplier


def _parse_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw_value = str(value).strip()
    if len(raw_value) == 8 and raw_value.isdigit():
        return datetime.strptime(raw_value, "%Y%m%d").date()
    return datetime.fromisoformat(raw_value).date()
