from __future__ import annotations

import importlib
import json
import math
import os
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

from fintech_quant.data.errors import MissingProviderCredential, MissingProviderDependency, ProviderFetchError
from fintech_quant.data.symbols import normalize_a_share_symbol
from fintech_quant.information.models import InformationCategory, InformationRecord


_MISSING = object()


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
    def __init__(self, fetchers: list[InformationFetcher], *, ignore_fetch_errors: bool = False) -> None:
        self._fetchers = fetchers
        self._ignore_fetch_errors = ignore_fetch_errors

    def fetch(
        self,
        symbol: str | None,
        sector: str | None,
        start: date,
        end: date,
    ) -> list[InformationRecord]:
        records: list[InformationRecord] = []
        for fetcher in self._fetchers:
            try:
                records.extend(fetcher.fetch(symbol, sector, start, end))
            except ProviderFetchError:
                if not self._ignore_fetch_errors:
                    raise
        return sorted(records, key=lambda record: (record.published_at, record.normalized_symbol or "", record.title))


class AkShareNoticeFetcher(InformationFetcher):
    """Fetch AkShare notice rows from recent pages and filter them locally by date."""

    def __init__(
        self,
        report_type: str = "重大事项",
        recent_page: int = 1,
        recent_pages: int = 1,
        fetcher: Callable[[], object] | None = None,
        page_fetcher: Callable[[int], object] | None = None,
    ) -> None:
        self._report_type = report_type
        self._recent_page = recent_page
        self._recent_pages = recent_pages
        self._fetcher = fetcher
        self._page_fetcher = page_fetcher

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
        self._validate_recent_pages()
        if self._fetcher is not None:
            return self._run_fetch(self._fetcher)
        if self._page_fetcher is not None:
            return self._fetch_page_range(self._page_fetcher)

        try:
            ak = importlib.import_module("akshare")
        except ImportError as exc:
            raise MissingProviderDependency("akshare is required for AkShareNoticeFetcher") from exc

        return self._fetch_page_range(
            lambda page: ak.stock_notice_report(
                report_type=self._report_type,
                recent_page=page,
            ).to_dict(orient="records")
        )

    def _run_fetch(self, fetcher: Callable[[], object]) -> list[dict[str, object]]:
        try:
            return list(fetcher())
        except Exception as exc:
            raise ProviderFetchError(
                f"akshare notice fetch failed for report_type={self._report_type!r}, recent_page={self._recent_page!r}"
            ) from exc

    def _fetch_page_range(self, fetcher: Callable[[int], object]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        try:
            for page in range(self._recent_page, self._recent_page + self._recent_pages):
                rows.extend(_rows_from_fetch_result(fetcher(page)))
        except Exception as exc:
            raise ProviderFetchError(
                f"akshare notice fetch failed for report_type={self._report_type!r}, recent_page={self._recent_page!r}, recent_pages={self._recent_pages!r}"
            ) from exc
        return rows

    def _validate_recent_pages(self) -> None:
        if self._recent_page <= 0:
            raise ValueError("recent_page must be positive")
        if self._recent_pages <= 0:
            raise ValueError("recent_pages must be positive")


class AkSharePolicyNewsFetcher(InformationFetcher):
    """Fetch policy-like CLS news rows and keep only rows relevant to the requested scope."""

    def __init__(
        self,
        news_symbol: str = "全部",
        fetcher: Callable[[], object] | None = None,
    ) -> None:
        self._news_symbol = news_symbol
        self._fetcher = fetcher

    def fetch(
        self,
        symbol: str | None,
        sector: str | None,
        start: date,
        end: date,
    ) -> list[InformationRecord]:
        normalized_symbol = normalize_a_share_symbol(symbol) if symbol else None
        try:
            records = [
                _record_from_policy_news_row(row, normalized_symbol, sector)
                for row in self._fetch_rows()
                if _is_policy_news_row(row) and _matches_policy_scope(row, normalized_symbol, sector)
            ]
        except Exception as exc:
            raise ProviderFetchError(f"akshare policy news fetch failed for symbol={self._news_symbol!r}") from exc
        return _filter_records(records, normalized_symbol, sector, start, end)

    def _fetch_rows(self) -> list[dict[str, object]]:
        if self._fetcher is not None:
            return _rows_from_fetch_result(self._fetcher())
        try:
            ak = importlib.import_module("akshare")
        except ImportError as exc:
            raise MissingProviderDependency("akshare is required for AkSharePolicyNewsFetcher") from exc
        return _rows_from_fetch_result(ak.stock_info_global_cls(symbol=self._news_symbol))


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


class AkShareFundamentalFetcher(InformationFetcher):
    def __init__(
        self,
        valuation_fetcher: Callable[[str], object] | None = None,
        financial_fetcher: Callable[[str], object] | None = None,
    ) -> None:
        self._valuation_fetcher = valuation_fetcher
        self._financial_fetcher = financial_fetcher

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
        plain_symbol = _plain_symbol(normalized_symbol)
        valuation_rows, valuation_error = self._fetch_optional_rows(self._fetch_valuation_rows, plain_symbol)
        financial_rows, financial_error = self._fetch_optional_rows(self._fetch_financial_rows, plain_symbol)
        if not valuation_rows and not financial_rows and (valuation_error or financial_error):
            details = "; ".join(error for error in (valuation_error, financial_error) if error)
            raise ProviderFetchError(f"akshare fundamental fetch failed for symbol={normalized_symbol!r}: {details}")
        records = _records_from_fundamental_rows(normalized_symbol, valuation_rows, financial_rows, end)
        return _filter_records(records, normalized_symbol, None, start, end)

    def _fetch_optional_rows(
        self,
        fetcher: Callable[[str], list[dict[str, object]]],
        symbol: str,
    ) -> tuple[list[dict[str, object]], str | None]:
        try:
            return fetcher(symbol), None
        except Exception as exc:
            return [], str(exc)

    def _fetch_valuation_rows(self, symbol: str) -> list[dict[str, object]]:
        if self._valuation_fetcher is not None:
            return _rows_from_fetch_result(self._valuation_fetcher(symbol))
        ak = _import_akshare("AkShareFundamentalFetcher")
        if hasattr(ak, "stock_a_indicator_lg"):
            return _rows_from_fetch_result(ak.stock_a_indicator_lg(symbol=symbol))
        rows = _rows_from_fetch_result(ak.stock_zh_a_spot_em())
        return [row for row in rows if str(row.get("代码", "")).strip() == symbol]

    def _fetch_financial_rows(self, symbol: str) -> list[dict[str, object]]:
        if self._financial_fetcher is not None:
            return _rows_from_fetch_result(self._financial_fetcher(symbol))
        ak = _import_akshare("AkShareFundamentalFetcher")
        return _rows_from_fetch_result(ak.stock_financial_analysis_indicator(symbol=symbol))


class TushareFundamentalFetcher(InformationFetcher):
    def __init__(
        self,
        token: str | None = None,
        daily_basic_fetcher: Callable[..., object] | None = None,
        financial_indicator_fetcher: Callable[..., object] | None = None,
    ) -> None:
        self._token = token if token is not None else os.getenv("TUSHARE_TOKEN", "")
        self._daily_basic_fetcher = daily_basic_fetcher
        self._financial_indicator_fetcher = financial_indicator_fetcher

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
        if not self._token.strip():
            raise MissingProviderCredential("TUSHARE_TOKEN is required for TushareFundamentalFetcher")
        normalized_symbol = normalize_a_share_symbol(symbol)
        try:
            daily_basic_rows = self._fetch_daily_basic_rows(normalized_symbol, start, end)
            financial_indicator_rows = self._fetch_financial_indicator_rows(normalized_symbol, start, end)
            records = _records_from_tushare_fundamental_rows(
                normalized_symbol,
                daily_basic_rows,
                financial_indicator_rows,
            )
        except MissingProviderDependency:
            raise
        except Exception as exc:
            raise ProviderFetchError(f"tushare fundamental fetch failed for symbol={normalized_symbol!r}") from exc
        return _filter_records(records, normalized_symbol, None, start, end)

    def _fetch_daily_basic_rows(self, symbol: str, start: date, end: date) -> list[dict[str, object]]:
        if self._daily_basic_fetcher is not None:
            return _rows_from_fetch_result(
                self._daily_basic_fetcher(symbol=symbol, start=start, end=end, token=self._token)
            )
        pro = self._load_pro_api()
        return _rows_from_fetch_result(
            pro.daily_basic(
                ts_code=symbol,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
        )

    def _fetch_financial_indicator_rows(self, symbol: str, start: date, end: date) -> list[dict[str, object]]:
        if self._financial_indicator_fetcher is not None:
            return _rows_from_fetch_result(
                self._financial_indicator_fetcher(symbol=symbol, start=start, end=end, token=self._token)
            )
        pro = self._load_pro_api()
        return _rows_from_fetch_result(
            pro.fina_indicator(
                ts_code=symbol,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
        )

    def _load_pro_api(self) -> object:
        try:
            ts = importlib.import_module("tushare")
        except ImportError as exc:
            raise MissingProviderDependency("tushare is required for TushareFundamentalFetcher") from exc
        return ts.pro_api(self._token)


class AkShareFinancialStatementFetcher(InformationFetcher):
    def __init__(
        self,
        statement_types: tuple[str, ...] = ("资产负债表", "利润表", "现金流量表"),
        fetcher: Callable[[str, str], object] | None = None,
    ) -> None:
        self._statement_types = statement_types
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
        stock = f"{_market_from_symbol(normalized_symbol)}{_plain_symbol(normalized_symbol)}"
        try:
            records = [
                _record_from_financial_statement_row(row, normalized_symbol, statement_type)
                for statement_type in self._statement_types
                for row in self._fetch_rows(stock, statement_type)
            ]
        except Exception as exc:
            raise ProviderFetchError(
                f"akshare financial-statement fetch failed for symbol={normalized_symbol!r}"
            ) from exc
        return _filter_records(records, normalized_symbol, None, start, end)

    def _fetch_rows(self, stock: str, statement_type: str) -> list[dict[str, object]]:
        if self._fetcher is not None:
            return _rows_from_fetch_result(self._fetcher(stock, statement_type))
        ak = _import_akshare("AkShareFinancialStatementFetcher")
        return _rows_from_fetch_result(ak.stock_financial_report_sina(stock=stock, symbol=statement_type))


class AkSharePledgeRatioFetcher(InformationFetcher):
    def __init__(
        self,
        *,
        as_of: date | None = None,
        fetcher: Callable[[], object] | None = None,
    ) -> None:
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
        if symbol is None:
            return []
        as_of = self._as_of or end
        if not start <= as_of <= end:
            return []
        normalized_symbol = normalize_a_share_symbol(symbol)
        try:
            records = [
                _record_from_pledge_ratio_row(row, normalized_symbol, as_of)
                for row in self._fetch_rows()
                if _row_matches_symbol(row, normalized_symbol)
            ]
        except Exception as exc:
            raise ProviderFetchError(
                f"akshare pledge-ratio fetch failed for symbol={normalized_symbol!r}"
            ) from exc
        return _filter_records(records, normalized_symbol, None, start, end)

    def _fetch_rows(self) -> list[dict[str, object]]:
        if self._fetcher is not None:
            return _rows_from_fetch_result(self._fetcher())
        ak = _import_akshare("AkSharePledgeRatioFetcher")
        return _rows_from_fetch_result(ak.stock_gpzy_pledge_ratio_em())


class AkShareStStatusFetcher(InformationFetcher):
    def __init__(
        self,
        *,
        as_of: date | None = None,
        fetcher: Callable[[], object] | None = None,
    ) -> None:
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
        if symbol is None:
            return []
        as_of = self._as_of or end
        if not start <= as_of <= end:
            return []
        normalized_symbol = normalize_a_share_symbol(symbol)
        try:
            records = [
                _record_from_st_status_row(row, normalized_symbol, as_of)
                for row in self._fetch_rows()
                if _row_matches_symbol(row, normalized_symbol) and _is_st_name(row)
            ]
        except Exception as exc:
            raise ProviderFetchError(
                f"akshare ST status fetch failed for symbol={normalized_symbol!r}"
            ) from exc
        return _filter_records(records, normalized_symbol, None, start, end)

    def _fetch_rows(self) -> list[dict[str, object]]:
        if self._fetcher is not None:
            return _rows_from_fetch_result(self._fetcher())
        ak = _import_akshare("AkShareStStatusFetcher")
        return _rows_from_fetch_result(ak.stock_zh_a_spot_em())


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
        metadata=dict(data.get("metadata", {})),
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


def _record_from_policy_news_row(
    row: dict[str, object],
    normalized_symbol: str | None,
    sector: str | None,
) -> InformationRecord:
    title = str(_first_value(row, "标题", "title")).strip()
    summary = str(_first_value(row, "内容", "摘要", "summary", "content", default="")).strip()
    text = f"{title} {summary}"
    tags = ["regulatory_policy"]
    if _contains_any(text, _POLICY_PRESSURE_KEYWORDS):
        tags.extend(["policy_pressure", "regulatory_risk"])
    return InformationRecord(
        symbol=normalized_symbol,
        sector=sector,
        published_at=_parse_date(_first_value(row, "发布时间", "时间", "日期", "publish_time", "date")),
        source="akshare_policy_news",
        category=InformationCategory.REGULATORY_POLICY,
        title=title,
        url=str(_first_value(row, "链接", "网址", "url", default="")).strip(),
        summary=summary,
        risk_tags=tuple(tags),
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


def _records_from_fundamental_rows(
    normalized_symbol: str,
    valuation_rows: list[dict[str, object]],
    financial_rows: list[dict[str, object]],
    fallback_date: date,
) -> list[InformationRecord]:
    valuation_by_date = {
        _parse_date(_first_value(row, "日期", "date", "trade_date", default=fallback_date)): row for row in valuation_rows
    }
    financial_by_date = {
        _parse_date(_first_value(row, "日期", "截止日期", "date", "report_date", default=fallback_date)): row for row in financial_rows
    }
    records: list[InformationRecord] = []
    for record_date in sorted(set(valuation_by_date) | set(financial_by_date)):
        valuation = valuation_by_date.get(record_date, {})
        financial = financial_by_date.get(record_date, {})
        pe = _float_or_none(_first_value(valuation, "市盈率", "市盈率-动态", "市盈率-TTM", "pe", "PE", default=None))
        pb = _float_or_none(_first_value(valuation, "市净率", "pb", "PB", default=None))
        roe_raw = _float_or_none(_first_value(financial, "净资产收益率", "净资产收益率(%)", "roe", "ROE", default=None))
        growth_raw = _float_or_none(
            _first_value(financial, "主营业务收入增长率", "主营业务收入增长率(%)", "营业收入同比增长率", "growth", default=None)
        )
        roe = _ratio_from_percent(roe_raw)
        growth = _ratio_from_percent(growth_raw)
        summary = _fundamental_summary(pe, pb, roe, growth)
        if not summary:
            continue
        records.append(
            InformationRecord(
                symbol=normalized_symbol,
                sector=None,
                published_at=record_date,
                source="akshare_fundamental",
                category=InformationCategory.STOCK_DATA,
                title=f"{normalized_symbol} fundamental snapshot",
                url="",
                summary=summary,
                risk_tags=("selected_universe", "fundamental"),
            )
        )
    return records


def _records_from_tushare_fundamental_rows(
    normalized_symbol: str,
    daily_basic_rows: list[dict[str, object]],
    financial_indicator_rows: list[dict[str, object]],
) -> list[InformationRecord]:
    daily_basic_by_date = {
        _parse_date(_first_value(row, "trade_date", "ann_date", "end_date", "date")): row for row in daily_basic_rows
    }
    financial_by_date = {
        _parse_date(_first_value(row, "end_date", "ann_date", "trade_date", "date")): row
        for row in financial_indicator_rows
    }
    records: list[InformationRecord] = []
    for record_date in sorted(set(daily_basic_by_date) | set(financial_by_date)):
        daily_basic = daily_basic_by_date.get(record_date, {})
        financial = financial_by_date.get(record_date, {})
        pe = _float_or_none(_first_value(daily_basic, "pe_ttm", "pe", default=None))
        pb = _float_or_none(_first_value(daily_basic, "pb", default=None))
        roe = _ratio_from_percent(_float_or_none(_first_value(financial, "roe_dt", "roe", default=None)))
        growth = _ratio_from_percent(
            _float_or_none(_first_value(financial, "revenue_yoy", "or_yoy", "tr_yoy", default=None))
        )
        summary = _fundamental_summary(pe, pb, roe, growth)
        if not summary:
            continue
        records.append(
            InformationRecord(
                symbol=normalized_symbol,
                sector=None,
                published_at=record_date,
                source="tushare_fundamental",
                category=InformationCategory.STOCK_DATA,
                title=f"{normalized_symbol} tushare fundamental snapshot",
                url="",
                summary=summary,
                risk_tags=("selected_universe", "fundamental", "tushare"),
            )
        )
    return records


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


def _record_from_financial_statement_row(
    row: dict[str, object],
    normalized_symbol: str,
    statement_type: str,
) -> InformationRecord:
    report_date = _parse_date(_first_value(row, "报告日", "报表日期", "截止日期", "日期", "report_date"))
    return InformationRecord(
        symbol=normalized_symbol,
        sector=None,
        published_at=report_date,
        source="akshare_financial_statement",
        category=InformationCategory.STOCK_DATA,
        title=f"{normalized_symbol} {statement_type} {report_date.isoformat()}",
        url="",
        summary=_financial_statement_summary(row),
        risk_tags=("selected_universe", "financial_statement", _statement_tag(statement_type)),
        metadata={"statement_type": statement_type, "raw_row": _metadata_row(row)},
    )


def _record_from_pledge_ratio_row(
    row: dict[str, object],
    normalized_symbol: str,
    as_of: date,
) -> InformationRecord:
    pledge_ratio = _ratio_from_percent(
        _float_or_none(_first_value(row, "质押比例", "质押总比例", "pledge_ratio", default=0.0))
    )
    pledge_ratio = 0.0 if pledge_ratio is None else pledge_ratio
    return InformationRecord(
        symbol=normalized_symbol,
        sector=None,
        published_at=as_of,
        source="akshare_pledge_ratio",
        category=InformationCategory.STOCK_DATA,
        title=f"{normalized_symbol} pledge ratio",
        url="",
        summary=f"pledge_ratio={pledge_ratio}",
        risk_tags=("selected_universe", "pledge_ratio"),
        metadata={"raw_row": _metadata_row(row)},
    )


def _record_from_st_status_row(
    row: dict[str, object],
    normalized_symbol: str,
    as_of: date,
) -> InformationRecord:
    stock_name = str(_first_optional_value(row, ("名称", "股票简称", "name")) or "").strip()
    return InformationRecord(
        symbol=normalized_symbol,
        sector=None,
        published_at=as_of,
        source="akshare_st_status",
        category=InformationCategory.STOCK_DATA,
        title=f"{normalized_symbol} ST status",
        url="",
        summary=f"st_warning=true; stock_name={stock_name}",
        risk_tags=("selected_universe", "st_warning"),
        metadata={"raw_row": _metadata_row(row)},
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


def _row_matches_symbol(row: dict[str, object], normalized_symbol: str) -> bool:
    raw_symbol = _first_optional_value(row, ("证券代码", "股票代码", "代码", "symbol"))
    if raw_symbol in (None, ""):
        return False
    return normalize_a_share_symbol(str(raw_symbol).strip()) == normalized_symbol


def _is_st_name(row: dict[str, object]) -> bool:
    stock_name = str(_first_optional_value(row, ("名称", "股票简称", "name")) or "").upper()
    return "ST" in stock_name


def _financial_statement_summary(row: dict[str, object]) -> str:
    summary_fields = (
        ("revenue", ("营业收入", "营业总收入", "主营业务收入")),
        ("net_profit", ("净利润", "归属于母公司所有者的净利润")),
        ("goodwill", ("商誉",)),
        ("total_assets", ("资产总计", "总资产")),
        ("total_liabilities", ("负债合计", "总负债")),
        ("operating_cash_flow", ("经营活动产生的现金流量净额", "经营现金流量净额")),
    )
    parts: list[str] = []
    for output_key, source_keys in summary_fields:
        value = _first_optional_value(row, source_keys)
        if value not in (None, ""):
            parts.append(f"{output_key}={value}")
    return "; ".join(parts)


def _first_optional_value(row: dict[str, object], keys: tuple[str, ...]) -> object | None:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _statement_tag(statement_type: str) -> str:
    if statement_type == "资产负债表":
        return "balance_sheet"
    if statement_type == "利润表":
        return "income_statement"
    if statement_type == "现金流量表":
        return "cash_flow_statement"
    return "financial_statement"


def _metadata_row(row: dict[str, object]) -> dict[str, object]:
    return {str(key): _metadata_value(value) for key, value in row.items()}


def _metadata_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


_POLICY_KEYWORDS = (
    "政策",
    "监管",
    "证监会",
    "交易所",
    "发改委",
    "工信部",
    "财政部",
    "央行",
    "银保监",
    "金融监管",
    "规范",
    "信息披露",
)

_POLICY_PRESSURE_KEYWORDS = (
    "处罚",
    "问询",
    "整改",
    "限制",
    "禁止",
    "退市",
    "严查",
    "整顿",
    "风险",
    "加强",
)


def _is_policy_news_row(row: dict[str, object]) -> bool:
    return _contains_any(_row_text(row), _POLICY_KEYWORDS)


def _matches_policy_scope(row: dict[str, object], normalized_symbol: str | None, sector: str | None) -> bool:
    text = _row_text(row)
    matches_symbol = True
    if normalized_symbol is not None:
        plain_symbol = _plain_symbol(normalized_symbol)
        matches_symbol = plain_symbol in text or normalized_symbol in text
    matches_sector = sector in text if sector else True
    return matches_symbol and matches_sector


def _row_text(row: dict[str, object]) -> str:
    return " ".join(str(value) for value in row.values() if value not in (None, ""))


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _import_akshare(consumer: str) -> object:
    try:
        return importlib.import_module("akshare")
    except ImportError as exc:
        raise MissingProviderDependency(f"akshare is required for {consumer}") from exc


def _rows_from_fetch_result(result: object) -> list[dict[str, object]]:
    if hasattr(result, "to_dict"):
        return list(result.to_dict(orient="records"))
    return [dict(row) for row in result]  # type: ignore[arg-type]


def _first_value(row: dict[str, object], *keys: str, default: object = _MISSING) -> object:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    if default is not _MISSING:
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


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    parsed = _float_value(value)
    if not math.isfinite(parsed):
        return None
    return parsed


def _ratio_from_percent(value: float | None) -> float | None:
    if value is None:
        return None
    if abs(value) > 1:
        return round(value / 100.0, 6)
    return value


def _fundamental_summary(
    pe: float | None,
    pb: float | None,
    roe: float | None,
    growth: float | None,
) -> str:
    parts = []
    for key, value in (("pe", pe), ("pb", pb), ("roe", roe), ("growth", growth)):
        if value is not None:
            parts.append(f"{key}={value}")
    return "; ".join(parts)


def _parse_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw_value = str(value).strip()
    if len(raw_value) == 8 and raw_value.isdigit():
        return datetime.strptime(raw_value, "%Y%m%d").date()
    return datetime.fromisoformat(raw_value).date()
