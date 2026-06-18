# A-Share Research System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first usable A-share research loop: normalized A-share data access, classified information storage, deterministic multi-dimensional scoring, risk warnings, drawdown accounting, and a score-based baseline strategy that future DQN work can benchmark against.

**Architecture:** Keep the existing package layout and add small focused modules. Data providers normalize records into local dictionaries, the information repository persists source-backed records with retention classes, the feature layer scores stocks, the risk layer emits warning actions, the drawdown engine accounts for equity risk, and the baseline strategy combines score plus risk action into buy/sell/hold decisions.

**Tech Stack:** Python 3.14, standard library dataclasses/enums/json/pathlib/datetime, existing `unittest` test runner, optional runtime imports for `akshare` and `tushare` hidden behind provider adapters.

## Global Constraints

- A-share first, daily frequency first, no high-frequency trading.
- AkShare is the primary data provider; Tushare has a token-ready adapter for future activation.
- Build around stable local schemas before adding extra fallback providers.
- Do not implement live brokerage trading in Phase 1.
- Do not deepen DQN training until data, baseline strategy, backtest, and risk-control loop are reliable.
- Information repository retention has two classes: text financial/report records keep only the most recent 3 years; selected-universe stock data records are retained without the 3-year pruning rule for RL training material.
- Use deterministic local fixtures for tests; core tests must not require network access.
- Keep trading logic simple, transparent, and auditable.
- Commit after each coherent, verified phase.
- Use the configured GitHub `origin` remote as the backup target when credentials allow pushing.
- Include a concise change report after each implementation phase with changed files, behavior added, verification commands, and known limitations.

---

## File Structure

- Create `src/fintech_quant/data/symbols.py`: normalize A-share symbols and infer exchange suffix.
- Create `src/fintech_quant/data/errors.py`: shared provider configuration and availability errors.
- Create `src/fintech_quant/data/registry.py`: provider registry with `source="auto"` routing.
- Modify `src/fintech_quant/data/base.py`: add normalized record helpers while preserving `MarketDataProvider.history`.
- Modify `src/fintech_quant/data/akshare_provider.py`: implement injectable AkShare daily history normalization.
- Create `src/fintech_quant/data/tushare_provider.py`: token-aware Tushare adapter boundary.
- Modify `src/fintech_quant/data/__init__.py`: export new data-layer interfaces.
- Create `src/fintech_quant/information/models.py`: information record dataclasses, categories, retention classes.
- Create `src/fintech_quant/information/repository.py`: JSONL-backed append/query/prune repository.
- Create `src/fintech_quant/information/fetchers.py`: script-oriented fetch result interface and deterministic in-memory fetcher for tests.
- Create `src/fintech_quant/information/__init__.py`: exports.
- Create `scripts/fetch_information.py`: CLI entry point for symbol/sector/date-range information fetch.
- Create `src/fintech_quant/backtesting/drawdown.py`: equity curve drawdown accounting.
- Modify `src/fintech_quant/backtesting/__init__.py`: export drawdown interfaces.
- Modify `src/fintech_quant/risk/rules.py`: expand risk limits and implement four-layer warnings.
- Modify `src/fintech_quant/risk/__init__.py`: export risk interfaces.
- Replace `src/fintech_quant/features/factors.py`: implement component scores and total weighted score.
- Modify `src/fintech_quant/features/__init__.py`: export scoring interfaces.
- Create `src/fintech_quant/strategies/scored_baseline.py`: score-and-risk baseline strategy.
- Modify `src/fintech_quant/strategies/__init__.py`: export baseline strategy.
- Create `tests/test_data_layer.py`: data normalization, registry, missing-token behavior.
- Create `tests/test_information_repository.py`: repository category and retention behavior.
- Create `tests/test_drawdown_engine.py`: rolling peak, drawdown, max drawdown, liquidation date.
- Create `tests/test_risk_engine.py`: requested warning rules and strictest action.
- Create `tests/test_scoring_pipeline.py`: 35/25/25/15 scoring behavior.
- Create `tests/test_scored_baseline_strategy.py`: baseline strategy respects risk before score.
- Modify `tests/test_project_contracts.py`: include Tushare in configured data sources and keep existing RL hold contract.

---

### Task 1: A-Share Data Layer Contracts

**Files:**
- Create: `src/fintech_quant/data/symbols.py`
- Create: `src/fintech_quant/data/errors.py`
- Create: `src/fintech_quant/data/registry.py`
- Modify: `src/fintech_quant/data/base.py`
- Modify: `src/fintech_quant/data/akshare_provider.py`
- Create: `src/fintech_quant/data/tushare_provider.py`
- Modify: `src/fintech_quant/data/__init__.py`
- Modify: `src/fintech_quant/config/__init__.py`
- Modify: `tests/test_project_contracts.py`
- Test: `tests/test_data_layer.py`

**Interfaces:**
- Produces: `normalize_a_share_symbol(symbol: str) -> str`
- Produces: `infer_a_share_exchange(code: str) -> str`
- Produces: `normalize_daily_bar(symbol: str, row: Mapping[str, object], source: str) -> dict[str, object]`
- Produces: `ProviderRegistry.register(provider: MarketDataProvider) -> None`
- Produces: `ProviderRegistry.get(source: str) -> MarketDataProvider`
- Produces: `ProviderRegistry.history(symbol: str, start: date, end: date, source: str = "auto") -> list[dict[str, object]]`
- Produces: `TushareProvider(token: str | None = None)`
- Consumes: existing `MarketDataProvider.history(symbol: str, start: date, end: date)`.

- [ ] **Step 1: Write the failing data-layer tests**

Create `tests/test_data_layer.py` with this content:

```python
from __future__ import annotations

import unittest
from datetime import date


class DataLayerTest(unittest.TestCase):
    def test_normalize_a_share_symbol_adds_exchange_suffix(self) -> None:
        from fintech_quant.data.symbols import normalize_a_share_symbol

        self.assertEqual(normalize_a_share_symbol("000001"), "000001.SZ")
        self.assertEqual(normalize_a_share_symbol("600000"), "600000.SH")
        self.assertEqual(normalize_a_share_symbol("688001"), "688001.SH")
        self.assertEqual(normalize_a_share_symbol("000001.sz"), "000001.SZ")

    def test_normalize_a_share_symbol_rejects_unknown_code(self) -> None:
        from fintech_quant.data.symbols import normalize_a_share_symbol

        with self.assertRaises(ValueError):
            normalize_a_share_symbol("123")

    def test_normalize_daily_bar_maps_common_chinese_columns(self) -> None:
        from fintech_quant.data.base import normalize_daily_bar

        row = {
            "日期": "2026-06-01",
            "开盘": "10.1",
            "最高": "10.8",
            "最低": "9.9",
            "收盘": "10.5",
            "成交量": "12345",
            "成交额": "67890.5",
        }

        self.assertEqual(
            normalize_daily_bar("000001", row, "akshare"),
            {
                "symbol": "000001.SZ",
                "trade_date": "2026-06-01",
                "open": 10.1,
                "high": 10.8,
                "low": 9.9,
                "close": 10.5,
                "volume": 12345.0,
                "amount": 67890.5,
                "source": "akshare",
            },
        )

    def test_provider_registry_auto_routes_a_share_to_akshare(self) -> None:
        from fintech_quant.data.base import MarketDataProvider
        from fintech_quant.data.registry import ProviderRegistry

        class FakeProvider(MarketDataProvider):
            name = "akshare"

            def history(self, symbol: str, start: date, end: date) -> list[dict[str, object]]:
                return [{"symbol": symbol, "trade_date": str(start), "source": self.name}]

        registry = ProviderRegistry()
        registry.register(FakeProvider())

        rows = registry.history("000001", date(2026, 1, 1), date(2026, 1, 2))

        self.assertEqual(rows, [{"symbol": "000001.SZ", "trade_date": "2026-01-01", "source": "akshare"}])

    def test_tushare_provider_requires_token_before_use(self) -> None:
        from fintech_quant.data.errors import MissingProviderCredential
        from fintech_quant.data.tushare_provider import TushareProvider

        provider = TushareProvider(token="")

        with self.assertRaises(MissingProviderCredential):
            provider.history("000001", date(2026, 1, 1), date(2026, 1, 2))


if __name__ == "__main__":
    unittest.main()
```

Modify `tests/test_project_contracts.py` so `test_default_settings_define_a_share_daily_research_scope` also asserts:

```python
        self.assertIn("tushare", settings.data_sources)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_data_layer tests.test_project_contracts
```

Expected: FAIL with `ModuleNotFoundError` for `fintech_quant.data.symbols` or missing `tushare` in `settings.data_sources`.

- [ ] **Step 3: Implement the minimal data-layer code**

Create `src/fintech_quant/data/errors.py`:

```python
from __future__ import annotations


class DataProviderError(RuntimeError):
    """Base error for market data provider failures."""


class MissingProviderCredential(DataProviderError):
    """Raised when a provider needs a credential that is not configured."""


class UnknownDataProvider(DataProviderError):
    """Raised when a requested provider is not registered."""
```

Create `src/fintech_quant/data/symbols.py`:

```python
from __future__ import annotations

import re

_A_SHARE_RE = re.compile(r"^(?P<code>\d{6})(?:\.(?P<exchange>SH|SZ|BJ))?$", re.IGNORECASE)


def infer_a_share_exchange(code: str) -> str:
    normalized = code.strip()
    if len(normalized) != 6 or not normalized.isdigit():
        raise ValueError(f"Invalid A-share code: {code!r}")
    if normalized.startswith(("60", "68", "90")):
        return "SH"
    if normalized.startswith(("00", "30", "20")):
        return "SZ"
    if normalized.startswith(("43", "83", "87", "92")):
        return "BJ"
    raise ValueError(f"Cannot infer A-share exchange for code: {code!r}")


def normalize_a_share_symbol(symbol: str) -> str:
    raw = symbol.strip().upper()
    match = _A_SHARE_RE.match(raw)
    if not match:
        raise ValueError(f"Invalid A-share symbol: {symbol!r}")
    code = match.group("code")
    exchange = match.group("exchange") or infer_a_share_exchange(code)
    return f"{code}.{exchange.upper()}"
```

Modify `src/fintech_quant/data/base.py` to:

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Mapping

from fintech_quant.data.symbols import normalize_a_share_symbol


class MarketDataProvider(ABC):
    name: str

    @abstractmethod
    def history(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        """Return daily bars or records for a symbol."""


def normalize_daily_bar(symbol: str, row: Mapping[str, object], source: str) -> dict[str, object]:
    trade_date = _first_present(row, ("trade_date", "date", "日期"))
    if trade_date is None:
        raise ValueError("Daily bar is missing trade_date/date/日期")
    return {
        "symbol": normalize_a_share_symbol(symbol),
        "trade_date": str(trade_date),
        "open": _float_value(_first_present(row, ("open", "开盘"))),
        "high": _float_value(_first_present(row, ("high", "最高"))),
        "low": _float_value(_first_present(row, ("low", "最低"))),
        "close": _float_value(_first_present(row, ("close", "收盘"))),
        "volume": _float_value(_first_present(row, ("volume", "成交量"))),
        "amount": _float_value(_first_present(row, ("amount", "成交额"))),
        "source": source,
    }


def _first_present(row: Mapping[str, object], keys: tuple[str, ...]) -> object | None:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _float_value(value: object | None) -> float | None:
    if value is None:
        return None
    return float(value)
```

Create `src/fintech_quant/data/registry.py`:

```python
from __future__ import annotations

from datetime import date

from fintech_quant.data.base import MarketDataProvider
from fintech_quant.data.errors import UnknownDataProvider
from fintech_quant.data.symbols import normalize_a_share_symbol


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, MarketDataProvider] = {}

    def register(self, provider: MarketDataProvider) -> None:
        self._providers[provider.name] = provider

    def get(self, source: str) -> MarketDataProvider:
        if source == "auto":
            source = "akshare"
        try:
            return self._providers[source]
        except KeyError as exc:
            raise UnknownDataProvider(f"Unknown data provider: {source}") from exc

    def history(
        self,
        symbol: str,
        start: date,
        end: date,
        source: str = "auto",
    ) -> list[dict[str, object]]:
        normalized_symbol = normalize_a_share_symbol(symbol)
        return self.get(source).history(normalized_symbol, start, end)
```

Modify `src/fintech_quant/data/akshare_provider.py` to:

```python
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from fintech_quant.data.base import MarketDataProvider, normalize_daily_bar
from fintech_quant.data.symbols import normalize_a_share_symbol


class AkShareProvider(MarketDataProvider):
    name = "akshare"

    def __init__(self, fetcher: Callable[..., Any] | None = None) -> None:
        self._fetcher = fetcher

    def history(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        normalized_symbol = normalize_a_share_symbol(symbol)
        rows = self._fetch(normalized_symbol, start, end)
        return [normalize_daily_bar(normalized_symbol, row, self.name) for row in rows]

    def _fetch(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        if self._fetcher is not None:
            return list(self._fetcher(symbol=symbol, start=start, end=end))
        import akshare as ak

        code = symbol.split(".")[0]
        frame = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="qfq",
        )
        return frame.to_dict(orient="records")
```

Create `src/fintech_quant/data/tushare_provider.py`:

```python
from __future__ import annotations

import os
from collections.abc import Callable
from datetime import date
from typing import Any

from fintech_quant.data.base import MarketDataProvider, normalize_daily_bar
from fintech_quant.data.errors import MissingProviderCredential
from fintech_quant.data.symbols import normalize_a_share_symbol


class TushareProvider(MarketDataProvider):
    name = "tushare"

    def __init__(
        self,
        token: str | None = None,
        fetcher: Callable[..., Any] | None = None,
    ) -> None:
        self._token = token if token is not None else os.getenv("TUSHARE_TOKEN", "")
        self._fetcher = fetcher

    def history(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        if not self._token.strip():
            raise MissingProviderCredential("TUSHARE_TOKEN is required for TushareProvider")
        normalized_symbol = normalize_a_share_symbol(symbol)
        rows = self._fetch(normalized_symbol, start, end)
        return [normalize_daily_bar(normalized_symbol, row, self.name) for row in rows]

    def _fetch(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        if self._fetcher is not None:
            return list(self._fetcher(symbol=symbol, start=start, end=end, token=self._token))
        import tushare as ts

        pro = ts.pro_api(self._token)
        frame = pro.daily(
            ts_code=symbol,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        return frame.to_dict(orient="records")
```

Modify `src/fintech_quant/data/__init__.py` to export:

```python
from fintech_quant.data.akshare_provider import AkShareProvider
from fintech_quant.data.base import MarketDataProvider, normalize_daily_bar
from fintech_quant.data.errors import DataProviderError, MissingProviderCredential, UnknownDataProvider
from fintech_quant.data.registry import ProviderRegistry
from fintech_quant.data.symbols import infer_a_share_exchange, normalize_a_share_symbol
from fintech_quant.data.tushare_provider import TushareProvider

__all__ = [
    "AkShareProvider",
    "DataProviderError",
    "MarketDataProvider",
    "MissingProviderCredential",
    "ProviderRegistry",
    "TushareProvider",
    "UnknownDataProvider",
    "infer_a_share_exchange",
    "normalize_a_share_symbol",
    "normalize_daily_bar",
]
```

Modify `src/fintech_quant/config/__init__.py` so `default_settings().data_sources` is:

```python
        data_sources=("akshare", "tushare", "yahoo", "finnhub"),
```

- [ ] **Step 4: Run tests to verify the data layer passes**

Run:

```bash
.venv/bin/python -m unittest tests.test_data_layer tests.test_project_contracts
```

Expected: PASS.

- [ ] **Step 5: Run full tests**

Run:

```bash
.venv/bin/python -m unittest discover -s tests
```

Expected: PASS.

- [ ] **Step 6: Commit and push**

Run:

```bash
git add src/fintech_quant/data src/fintech_quant/config/__init__.py tests/test_data_layer.py tests/test_project_contracts.py
git commit -m "feat: add a-share data provider contracts"
git push origin main
```

Expected: commit succeeds and push updates `origin/main`.

Change report:

```text
Changed files: data providers, config, data-layer tests.
Behavior added: A-share symbol normalization, daily bar normalization, provider registry, AkShare adapter boundary, Tushare token boundary.
Verification: .venv/bin/python -m unittest discover -s tests
Known limitations: live AkShare/Tushare calls are adapter boundaries only; core tests use local fixtures.
```

---

### Task 2: Classified Information Repository

**Files:**
- Create: `src/fintech_quant/information/models.py`
- Create: `src/fintech_quant/information/repository.py`
- Create: `src/fintech_quant/information/fetchers.py`
- Create: `src/fintech_quant/information/__init__.py`
- Create: `scripts/fetch_information.py`
- Test: `tests/test_information_repository.py`

**Interfaces:**
- Consumes: `normalize_a_share_symbol(symbol: str) -> str` from Task 1.
- Produces: `InformationCategory`, `RetentionClass`, `InformationRecord`.
- Produces: `InformationRepository.append(record: InformationRecord) -> bool`.
- Produces: `InformationRepository.query(symbol: str | None = None, sector: str | None = None, category: InformationCategory | None = None) -> list[InformationRecord]`.
- Produces: `InformationRepository.prune_text_records(today: date) -> int`.
- Produces: `InformationFetcher.fetch(symbol: str | None, sector: str | None, start: date, end: date) -> list[InformationRecord]`.

- [ ] **Step 1: Write the failing repository tests**

Create `tests/test_information_repository.py`:

```python
from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path


class InformationRepositoryTest(unittest.TestCase):
    def test_append_deduplicates_by_stable_key(self) -> None:
        from fintech_quant.information import InformationCategory, InformationRecord, InformationRepository

        with tempfile.TemporaryDirectory() as tmp:
            repo = InformationRepository(Path(tmp) / "info.jsonl")
            record = InformationRecord(
                symbol="000001",
                sector=None,
                published_at=date(2026, 1, 2),
                source="exchange",
                category=InformationCategory.FINANCIAL_REPORT,
                title="Annual report",
                url="https://example.test/report",
                summary="Revenue grew.",
                risk_tags=("financial_report",),
            )

            self.assertTrue(repo.append(record))
            self.assertFalse(repo.append(record))
            self.assertEqual(len(repo.query(symbol="000001")), 1)

    def test_prune_text_records_keeps_recent_three_years_only(self) -> None:
        from fintech_quant.information import InformationCategory, InformationRecord, InformationRepository

        with tempfile.TemporaryDirectory() as tmp:
            repo = InformationRepository(Path(tmp) / "info.jsonl")
            old_text = InformationRecord(
                symbol="000001",
                sector=None,
                published_at=date(2022, 1, 1),
                source="exchange",
                category=InformationCategory.COMPANY_ANNOUNCEMENT,
                title="Old announcement",
                url="https://example.test/old",
                summary="Old text.",
                risk_tags=(),
            )
            recent_text = InformationRecord(
                symbol="000001",
                sector=None,
                published_at=date(2025, 6, 18),
                source="exchange",
                category=InformationCategory.COMPANY_ANNOUNCEMENT,
                title="Recent announcement",
                url="https://example.test/recent",
                summary="Recent text.",
                risk_tags=(),
            )

            repo.append(old_text)
            repo.append(recent_text)

            removed = repo.prune_text_records(today=date(2026, 6, 18))

            self.assertEqual(removed, 1)
            self.assertEqual([record.title for record in repo.query(symbol="000001")], ["Recent announcement"])

    def test_selected_universe_stock_data_is_not_pruned_by_text_policy(self) -> None:
        from fintech_quant.information import InformationCategory, InformationRecord, InformationRepository

        with tempfile.TemporaryDirectory() as tmp:
            repo = InformationRepository(Path(tmp) / "info.jsonl")
            old_stock_data = InformationRecord(
                symbol="000001",
                sector=None,
                published_at=date(2019, 1, 1),
                source="local",
                category=InformationCategory.STOCK_DATA,
                title="Selected universe training row",
                url="",
                summary="Retained for RL.",
                risk_tags=("selected_universe",),
            )

            repo.append(old_stock_data)
            removed = repo.prune_text_records(today=date(2026, 6, 18))

            self.assertEqual(removed, 0)
            self.assertEqual(len(repo.query(symbol="000001")), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_information_repository
```

Expected: FAIL with `ModuleNotFoundError` for `fintech_quant.information`.

- [ ] **Step 3: Implement models, repository, fetcher boundary, and script**

Create `src/fintech_quant/information/models.py`:

```python
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from enum import Enum

from fintech_quant.data.symbols import normalize_a_share_symbol


class InformationCategory(Enum):
    REGULATORY_POLICY = "regulatory_policy"
    FINANCIAL_REPORT = "financial_report"
    COMPANY_ANNOUNCEMENT = "company_announcement"
    SECTOR_EVENT = "sector_event"
    MARKET_SENTIMENT = "market_sentiment"
    STOCK_DATA = "stock_data"


class RetentionClass(Enum):
    TEXT_FINANCIAL_REPORT = "text_financial_report"
    SELECTED_UNIVERSE_STOCK_DATA = "selected_universe_stock_data"


TEXT_CATEGORIES = {
    InformationCategory.REGULATORY_POLICY,
    InformationCategory.FINANCIAL_REPORT,
    InformationCategory.COMPANY_ANNOUNCEMENT,
    InformationCategory.SECTOR_EVENT,
    InformationCategory.MARKET_SENTIMENT,
}


@dataclass(frozen=True)
class InformationRecord:
    symbol: str | None
    sector: str | None
    published_at: date
    source: str
    category: InformationCategory
    title: str
    url: str
    summary: str
    risk_tags: tuple[str, ...] = ()

    @property
    def normalized_symbol(self) -> str | None:
        return normalize_a_share_symbol(self.symbol) if self.symbol else None

    @property
    def retention_class(self) -> RetentionClass:
        if self.category is InformationCategory.STOCK_DATA:
            return RetentionClass.SELECTED_UNIVERSE_STOCK_DATA
        return RetentionClass.TEXT_FINANCIAL_REPORT

    @property
    def record_id(self) -> str:
        payload = "|".join(
            [
                self.source,
                self.url,
                self.title,
                self.normalized_symbol or "",
                self.sector or "",
                self.published_at.isoformat(),
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

Create `src/fintech_quant/information/repository.py`:

```python
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from fintech_quant.data.symbols import normalize_a_share_symbol
from fintech_quant.information.models import InformationCategory, InformationRecord, RetentionClass


class InformationRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: InformationRecord) -> bool:
        existing_ids = {item.record_id for item in self._read_all()}
        if record.record_id in existing_ids:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(self._to_json(record), ensure_ascii=False, sort_keys=True) + "\n")
        return True

    def query(
        self,
        symbol: str | None = None,
        sector: str | None = None,
        category: InformationCategory | None = None,
    ) -> list[InformationRecord]:
        normalized_symbol = normalize_a_share_symbol(symbol) if symbol else None
        records = self._read_all()
        if normalized_symbol is not None:
            records = [record for record in records if record.normalized_symbol == normalized_symbol]
        if sector is not None:
            records = [record for record in records if record.sector == sector]
        if category is not None:
            records = [record for record in records if record.category is category]
        return sorted(records, key=lambda record: record.published_at)

    def prune_text_records(self, today: date) -> int:
        cutoff = date(today.year - 3, today.month, today.day)
        records = self._read_all()
        kept = [
            record
            for record in records
            if record.retention_class is RetentionClass.SELECTED_UNIVERSE_STOCK_DATA
            or record.published_at >= cutoff
        ]
        removed = len(records) - len(kept)
        self._write_all(kept)
        return removed

    def _read_all(self) -> list[InformationRecord]:
        if not self.path.exists():
            return []
        records: list[InformationRecord] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    records.append(self._from_json(json.loads(line)))
        return records

    def _write_all(self, records: list[InformationRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(self._to_json(record), ensure_ascii=False, sort_keys=True) + "\n")

    def _to_json(self, record: InformationRecord) -> dict[str, object]:
        data = asdict(record)
        data["symbol"] = record.normalized_symbol
        data["published_at"] = record.published_at.isoformat()
        data["category"] = record.category.value
        data["retention_class"] = record.retention_class.value
        data["record_id"] = record.record_id
        return data

    def _from_json(self, data: dict[str, object]) -> InformationRecord:
        return InformationRecord(
            symbol=data.get("symbol") if isinstance(data.get("symbol"), str) else None,
            sector=data.get("sector") if isinstance(data.get("sector"), str) else None,
            published_at=date.fromisoformat(str(data["published_at"])),
            source=str(data["source"]),
            category=InformationCategory(str(data["category"])),
            title=str(data["title"]),
            url=str(data.get("url", "")),
            summary=str(data.get("summary", "")),
            risk_tags=tuple(data.get("risk_tags", ())),
        )
```

Create `src/fintech_quant/information/fetchers.py`:

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from fintech_quant.information.models import InformationRecord


class InformationFetcher(ABC):
    @abstractmethod
    def fetch(
        self,
        *,
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
        *,
        symbol: str | None,
        sector: str | None,
        start: date,
        end: date,
    ) -> list[InformationRecord]:
        return [
            record
            for record in self._records
            if start <= record.published_at <= end
            and (symbol is None or record.normalized_symbol == symbol or record.symbol == symbol)
            and (sector is None or record.sector == sector)
        ]
```

Create `src/fintech_quant/information/__init__.py`:

```python
from fintech_quant.information.fetchers import InformationFetcher, StaticInformationFetcher
from fintech_quant.information.models import InformationCategory, InformationRecord, RetentionClass
from fintech_quant.information.repository import InformationRepository

__all__ = [
    "InformationCategory",
    "InformationFetcher",
    "InformationRecord",
    "InformationRepository",
    "RetentionClass",
    "StaticInformationFetcher",
]
```

Create `scripts/fetch_information.py`:

```python
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
```

- [ ] **Step 4: Run repository tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_information_repository
```

Expected: PASS.

- [ ] **Step 5: Run full tests**

Run:

```bash
.venv/bin/python -m unittest discover -s tests
```

Expected: PASS.

- [ ] **Step 6: Commit and push**

Run:

```bash
git add src/fintech_quant/information scripts/fetch_information.py tests/test_information_repository.py
git commit -m "feat: add classified information repository"
git push origin main
```

Expected: commit succeeds and push updates `origin/main`.

Change report:

```text
Changed files: information models, repository, fetcher boundary, fetch script, repository tests.
Behavior added: classified information records, stable deduplication, text record 3-year pruning, selected-universe stock-data retention for RL.
Verification: .venv/bin/python -m unittest discover -s tests
Known limitations: fetch script uses an empty static fetcher until live source-specific fetchers are added.
```

---

### Task 3: Drawdown Engine

**Files:**
- Create: `src/fintech_quant/backtesting/drawdown.py`
- Modify: `src/fintech_quant/backtesting/__init__.py`
- Test: `tests/test_drawdown_engine.py`

**Interfaces:**
- Produces: `EquityPoint(trade_date: date, equity: float)`.
- Produces: `DrawdownPoint(trade_date: date, equity: float, rolling_peak: float, drawdown: float)`.
- Produces: `DrawdownResult(points: list[DrawdownPoint], max_drawdown: float, liquidation_date: date | None)`.
- Produces: `calculate_drawdown(points: Sequence[EquityPoint], liquidation_threshold: float = 0.15) -> DrawdownResult`.

- [ ] **Step 1: Write the failing drawdown tests**

Create `tests/test_drawdown_engine.py`:

```python
from __future__ import annotations

import unittest
from datetime import date


class DrawdownEngineTest(unittest.TestCase):
    def test_calculates_rolling_peak_drawdown_and_liquidation_date(self) -> None:
        from fintech_quant.backtesting.drawdown import EquityPoint, calculate_drawdown

        result = calculate_drawdown(
            [
                EquityPoint(date(2026, 1, 1), 100.0),
                EquityPoint(date(2026, 1, 2), 110.0),
                EquityPoint(date(2026, 1, 3), 99.0),
                EquityPoint(date(2026, 1, 4), 90.0),
            ],
            liquidation_threshold=0.15,
        )

        self.assertEqual([point.rolling_peak for point in result.points], [100.0, 110.0, 110.0, 110.0])
        self.assertEqual([round(point.drawdown, 4) for point in result.points], [0.0, 0.0, 0.1, 0.1818])
        self.assertAlmostEqual(result.max_drawdown, 0.1818, places=4)
        self.assertEqual(result.liquidation_date, date(2026, 1, 4))

    def test_rejects_empty_equity_curve(self) -> None:
        from fintech_quant.backtesting.drawdown import calculate_drawdown

        with self.assertRaises(ValueError):
            calculate_drawdown([])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_drawdown_engine
```

Expected: FAIL with `ModuleNotFoundError` for `fintech_quant.backtesting.drawdown`.

- [ ] **Step 3: Implement the drawdown engine**

Create `src/fintech_quant/backtesting/drawdown.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence


@dataclass(frozen=True)
class EquityPoint:
    trade_date: date
    equity: float


@dataclass(frozen=True)
class DrawdownPoint:
    trade_date: date
    equity: float
    rolling_peak: float
    drawdown: float


@dataclass(frozen=True)
class DrawdownResult:
    points: list[DrawdownPoint]
    max_drawdown: float
    liquidation_date: date | None


def calculate_drawdown(
    points: Sequence[EquityPoint],
    liquidation_threshold: float = 0.15,
) -> DrawdownResult:
    if not points:
        raise ValueError("Equity curve must contain at least one point")

    ordered = sorted(points, key=lambda point: point.trade_date)
    rolling_peak = ordered[0].equity
    max_drawdown = 0.0
    liquidation_date: date | None = None
    drawdown_points: list[DrawdownPoint] = []

    for point in ordered:
        rolling_peak = max(rolling_peak, point.equity)
        drawdown = 0.0 if rolling_peak == 0 else (rolling_peak - point.equity) / rolling_peak
        max_drawdown = max(max_drawdown, drawdown)
        if liquidation_date is None and drawdown >= liquidation_threshold:
            liquidation_date = point.trade_date
        drawdown_points.append(
            DrawdownPoint(
                trade_date=point.trade_date,
                equity=point.equity,
                rolling_peak=rolling_peak,
                drawdown=drawdown,
            )
        )

    return DrawdownResult(
        points=drawdown_points,
        max_drawdown=max_drawdown,
        liquidation_date=liquidation_date,
    )
```

Modify `src/fintech_quant/backtesting/__init__.py`:

```python
from fintech_quant.backtesting.drawdown import (
    DrawdownPoint,
    DrawdownResult,
    EquityPoint,
    calculate_drawdown,
)

__all__ = [
    "DrawdownPoint",
    "DrawdownResult",
    "EquityPoint",
    "calculate_drawdown",
]
```

- [ ] **Step 4: Run drawdown tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_drawdown_engine
```

Expected: PASS.

- [ ] **Step 5: Run full tests**

Run:

```bash
.venv/bin/python -m unittest discover -s tests
```

Expected: PASS.

- [ ] **Step 6: Commit and push**

Run:

```bash
git add src/fintech_quant/backtesting tests/test_drawdown_engine.py
git commit -m "feat: add drawdown engine"
git push origin main
```

Expected: commit succeeds and push updates `origin/main`.

Change report:

```text
Changed files: drawdown engine and tests.
Behavior added: equity curve drawdown, rolling peak, max drawdown, liquidation trigger date.
Verification: .venv/bin/python -m unittest discover -s tests
Known limitations: this is portfolio accounting only; full trade matching remains outside Phase 1.
```

---

### Task 4: Four-Layer Risk Warning Engine

**Files:**
- Modify: `src/fintech_quant/risk/rules.py`
- Modify: `src/fintech_quant/risk/__init__.py`
- Test: `tests/test_risk_engine.py`

**Interfaces:**
- Consumes: `RiskLimits` from existing risk module.
- Produces: `RiskAction` enum with `NONE`, `WATCH`, `REDUCE`, `LIQUIDATE`.
- Produces: `RiskWarning(layer: str, rule: str, action: RiskAction, message: str)`.
- Produces: `RiskInput(...)`.
- Produces: `evaluate_risk(risk_input: RiskInput, limits: RiskLimits = RiskLimits()) -> RiskEvaluation`.

- [ ] **Step 1: Write the failing risk tests**

Create `tests/test_risk_engine.py`:

```python
from __future__ import annotations

import unittest


class RiskEngineTest(unittest.TestCase):
    def test_portfolio_drawdown_15_percent_forces_liquidation(self) -> None:
        from fintech_quant.risk import RiskAction, RiskInput, evaluate_risk

        result = evaluate_risk(RiskInput(portfolio_drawdown=0.15))

        self.assertEqual(result.action, RiskAction.LIQUIDATE)
        self.assertIn("portfolio_drawdown", {warning.rule for warning in result.warnings})

    def test_single_stock_and_event_risks_emit_reduce_or_watch(self) -> None:
        from fintech_quant.risk import RiskAction, RiskInput, evaluate_risk

        result = evaluate_risk(
            RiskInput(
                single_position_drawdown=0.081,
                st_warning=True,
                goodwill_ratio=0.31,
                pledge_ratio=0.51,
                main_outflow_days=4,
            )
        )

        self.assertEqual(result.action, RiskAction.REDUCE)
        self.assertEqual(
            {warning.rule for warning in result.warnings},
            {
                "single_position_drawdown",
                "st_warning",
                "goodwill_ratio",
                "pledge_ratio",
                "main_outflow_days",
            },
        )

    def test_market_and_systemic_risks_emit_expected_actions(self) -> None:
        from fintech_quant.risk import RiskAction, RiskInput, evaluate_risk

        result = evaluate_risk(
            RiskInput(
                index_below_annual_ma=True,
                broad_market_drop_count=16,
            )
        )

        self.assertEqual(result.action, RiskAction.REDUCE)
        self.assertEqual(
            {warning.rule for warning in result.warnings},
            {"index_below_annual_ma", "broad_market_drop_count"},
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_risk_engine
```

Expected: FAIL with import errors for `RiskAction`, `RiskInput`, or `evaluate_risk`.

- [ ] **Step 3: Implement risk rules**

Replace `src/fintech_quant/risk/rules.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RiskAction(Enum):
    NONE = "none"
    WATCH = "watch"
    REDUCE = "reduce"
    LIQUIDATE = "liquidate"


_ACTION_RANK = {
    RiskAction.NONE: 0,
    RiskAction.WATCH: 1,
    RiskAction.REDUCE: 2,
    RiskAction.LIQUIDATE: 3,
}


@dataclass(frozen=True)
class RiskLimits:
    max_position_weight: float = 0.1
    max_portfolio_drawdown: float = 0.15
    max_single_position_drawdown: float = 0.08
    max_goodwill_ratio: float = 0.30
    max_pledge_ratio: float = 0.50
    max_main_outflow_days: int = 3
    broad_market_drop_threshold: int = 15


@dataclass(frozen=True)
class RiskInput:
    portfolio_drawdown: float = 0.0
    single_position_drawdown: float = 0.0
    st_warning: bool = False
    goodwill_ratio: float = 0.0
    pledge_ratio: float = 0.0
    main_outflow_days: int = 0
    index_below_annual_ma: bool = False
    broad_market_drop_count: int = 0


@dataclass(frozen=True)
class RiskWarning:
    layer: str
    rule: str
    action: RiskAction
    message: str


@dataclass(frozen=True)
class RiskEvaluation:
    action: RiskAction
    warnings: list[RiskWarning]


def evaluate_risk(
    risk_input: RiskInput,
    limits: RiskLimits = RiskLimits(),
) -> RiskEvaluation:
    warnings: list[RiskWarning] = []

    if risk_input.portfolio_drawdown >= limits.max_portfolio_drawdown:
        warnings.append(
            RiskWarning(
                layer="portfolio_drawdown",
                rule="portfolio_drawdown",
                action=RiskAction.LIQUIDATE,
                message="Portfolio drawdown reached liquidation threshold.",
            )
        )

    if risk_input.single_position_drawdown > limits.max_single_position_drawdown:
        warnings.append(
            RiskWarning(
                layer="single_stock_negative",
                rule="single_position_drawdown",
                action=RiskAction.REDUCE,
                message="Single position drawdown exceeded risk threshold.",
            )
        )

    if risk_input.st_warning:
        warnings.append(
            RiskWarning(
                layer="single_stock_negative",
                rule="st_warning",
                action=RiskAction.REDUCE,
                message="ST warning is active for the stock.",
            )
        )

    if risk_input.goodwill_ratio > limits.max_goodwill_ratio:
        warnings.append(
            RiskWarning(
                layer="single_stock_negative",
                rule="goodwill_ratio",
                action=RiskAction.WATCH,
                message="Goodwill ratio exceeded watch threshold.",
            )
        )

    if risk_input.pledge_ratio > limits.max_pledge_ratio:
        warnings.append(
            RiskWarning(
                layer="single_stock_negative",
                rule="pledge_ratio",
                action=RiskAction.WATCH,
                message="Share pledge ratio exceeded watch threshold.",
            )
        )

    if risk_input.main_outflow_days > limits.max_main_outflow_days:
        warnings.append(
            RiskWarning(
                layer="single_stock_negative",
                rule="main_outflow_days",
                action=RiskAction.WATCH,
                message="Main capital outflow continued beyond threshold.",
            )
        )

    if risk_input.index_below_annual_ma:
        warnings.append(
            RiskWarning(
                layer="broad_market_abnormal",
                rule="index_below_annual_ma",
                action=RiskAction.WATCH,
                message="Broad index is below the 250-day moving average.",
            )
        )

    if risk_input.broad_market_drop_count > limits.broad_market_drop_threshold:
        warnings.append(
            RiskWarning(
                layer="systemic_risk",
                rule="broad_market_drop_count",
                action=RiskAction.REDUCE,
                message="More than 15 tracked names fell over 3% in one day.",
            )
        )

    action = _strictest_action([warning.action for warning in warnings])
    return RiskEvaluation(action=action, warnings=warnings)


def _strictest_action(actions: list[RiskAction]) -> RiskAction:
    if not actions:
        return RiskAction.NONE
    return max(actions, key=lambda action: _ACTION_RANK[action])
```

Modify `src/fintech_quant/risk/__init__.py`:

```python
from fintech_quant.risk.rules import (
    RiskAction,
    RiskEvaluation,
    RiskInput,
    RiskLimits,
    RiskWarning,
    evaluate_risk,
)

__all__ = [
    "RiskAction",
    "RiskEvaluation",
    "RiskInput",
    "RiskLimits",
    "RiskWarning",
    "evaluate_risk",
]
```

- [ ] **Step 4: Run risk tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_risk_engine
```

Expected: PASS.

- [ ] **Step 5: Run full tests**

Run:

```bash
.venv/bin/python -m unittest discover -s tests
```

Expected: PASS.

- [ ] **Step 6: Commit and push**

Run:

```bash
git add src/fintech_quant/risk tests/test_risk_engine.py
git commit -m "feat: add risk warning engine"
git push origin main
```

Expected: commit succeeds and push updates `origin/main`.

Change report:

```text
Changed files: risk rules and tests.
Behavior added: four-layer risk warnings, strictest action selection, user-requested thresholds.
Verification: .venv/bin/python -m unittest discover -s tests
Known limitations: risk inputs are supplied by fixtures or callers; live factor/source hydration is handled by data and scoring modules.
```

---

### Task 5: Multi-Dimensional Scoring Pipeline

**Files:**
- Replace: `src/fintech_quant/features/factors.py`
- Modify: `src/fintech_quant/features/__init__.py`
- Test: `tests/test_scoring_pipeline.py`

**Interfaces:**
- Produces: `ComponentScore(name: str, score: float, max_score: float, reasons: tuple[str, ...])`.
- Produces: `StockScore(symbol: str, total: float, components: dict[str, ComponentScore], confidence: float, missing_fields: tuple[str, ...])`.
- Produces: `ScoreInput(...)`.
- Produces: `score_stock(score_input: ScoreInput) -> StockScore`.
- Consumes: no network data; caller supplies normalized metrics.

- [ ] **Step 1: Write the failing scoring tests**

Create `tests/test_scoring_pipeline.py`:

```python
from __future__ import annotations

import unittest


class ScoringPipelineTest(unittest.TestCase):
    def test_scores_components_using_required_weights(self) -> None:
        from fintech_quant.features import ScoreInput, score_stock

        result = score_stock(
            ScoreInput(
                symbol="000001",
                pe=18.0,
                pb=1.5,
                roe=0.16,
                growth=0.12,
                close_above_ma20=True,
                close_above_ma60=True,
                rsi=55.0,
                macd_positive=True,
                volume_confirmed=True,
                main_net_inflow=1.0,
                main_outflow_days=0,
                margin_financing_positive=True,
                limit_up_streak=1,
                dragon_tiger_positive=True,
                negative_event_count=0,
            )
        )

        self.assertEqual(result.symbol, "000001.SZ")
        self.assertEqual(result.total, 100.0)
        self.assertEqual(result.components["fundamental"].max_score, 35.0)
        self.assertEqual(result.components["technical"].max_score, 25.0)
        self.assertEqual(result.components["capital_flow"].max_score, 25.0)
        self.assertEqual(result.components["sentiment"].max_score, 15.0)

    def test_missing_fields_reduce_confidence_without_fabricating_score(self) -> None:
        from fintech_quant.features import ScoreInput, score_stock

        result = score_stock(ScoreInput(symbol="000001"))

        self.assertLess(result.total, 100.0)
        self.assertLess(result.confidence, 1.0)
        self.assertIn("pe", result.missing_fields)
        self.assertIn("rsi", result.missing_fields)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_scoring_pipeline
```

Expected: FAIL with import errors for `ScoreInput` or `score_stock`.

- [ ] **Step 3: Implement scoring pipeline**

Replace `src/fintech_quant/features/factors.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass

from fintech_quant.data.symbols import normalize_a_share_symbol


@dataclass(frozen=True)
class ScoreInput:
    symbol: str
    pe: float | None = None
    pb: float | None = None
    roe: float | None = None
    growth: float | None = None
    close_above_ma20: bool | None = None
    close_above_ma60: bool | None = None
    rsi: float | None = None
    macd_positive: bool | None = None
    volume_confirmed: bool | None = None
    main_net_inflow: float | None = None
    main_outflow_days: int | None = None
    margin_financing_positive: bool | None = None
    limit_up_streak: int | None = None
    dragon_tiger_positive: bool | None = None
    negative_event_count: int | None = None


@dataclass(frozen=True)
class ComponentScore:
    name: str
    score: float
    max_score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class StockScore:
    symbol: str
    total: float
    components: dict[str, ComponentScore]
    confidence: float
    missing_fields: tuple[str, ...]


def factor_pipeline_name() -> str:
    return "a_share_daily_factor_pipeline_v0"


def score_stock(score_input: ScoreInput) -> StockScore:
    missing: list[str] = []
    components = {
        "fundamental": _fundamental_score(score_input, missing),
        "technical": _technical_score(score_input, missing),
        "capital_flow": _capital_flow_score(score_input, missing),
        "sentiment": _sentiment_score(score_input, missing),
    }
    total = round(sum(component.score for component in components.values()), 4)
    expected_fields = 15
    confidence = round((expected_fields - len(set(missing))) / expected_fields, 4)
    return StockScore(
        symbol=normalize_a_share_symbol(score_input.symbol),
        total=total,
        components=components,
        confidence=max(0.0, confidence),
        missing_fields=tuple(sorted(set(missing))),
    )


def _fundamental_score(score_input: ScoreInput, missing: list[str]) -> ComponentScore:
    score = 0.0
    reasons: list[str] = []
    if score_input.pe is None:
        missing.append("pe")
    elif 0 < score_input.pe <= 30:
        score += 8.75
        reasons.append("PE is within the sanity band.")
    if score_input.pb is None:
        missing.append("pb")
    elif 0 < score_input.pb <= 3:
        score += 8.75
        reasons.append("PB is within the sanity band.")
    if score_input.roe is None:
        missing.append("roe")
    elif score_input.roe >= 0.12:
        score += 8.75
        reasons.append("ROE is above 12%.")
    if score_input.growth is None:
        missing.append("growth")
    elif score_input.growth >= 0.08:
        score += 8.75
        reasons.append("Growth is above 8%.")
    return ComponentScore("fundamental", score, 35.0, tuple(reasons))


def _technical_score(score_input: ScoreInput, missing: list[str]) -> ComponentScore:
    score = 0.0
    reasons: list[str] = []
    score += _bool_points(score_input.close_above_ma20, "close_above_ma20", 5.0, missing, reasons)
    score += _bool_points(score_input.close_above_ma60, "close_above_ma60", 5.0, missing, reasons)
    if score_input.rsi is None:
        missing.append("rsi")
    elif 45 <= score_input.rsi <= 65:
        score += 5.0
        reasons.append("RSI is in a healthy trend range.")
    score += _bool_points(score_input.macd_positive, "macd_positive", 5.0, missing, reasons)
    score += _bool_points(score_input.volume_confirmed, "volume_confirmed", 5.0, missing, reasons)
    return ComponentScore("technical", score, 25.0, tuple(reasons))


def _capital_flow_score(score_input: ScoreInput, missing: list[str]) -> ComponentScore:
    score = 0.0
    reasons: list[str] = []
    if score_input.main_net_inflow is None:
        missing.append("main_net_inflow")
    elif score_input.main_net_inflow > 0:
        score += 10.0
        reasons.append("Main capital is net inflow.")
    if score_input.main_outflow_days is None:
        missing.append("main_outflow_days")
    elif score_input.main_outflow_days <= 3:
        score += 7.5
        reasons.append("Main capital outflow is not persistent.")
    score += _bool_points(score_input.margin_financing_positive, "margin_financing_positive", 7.5, missing, reasons)
    return ComponentScore("capital_flow", score, 25.0, tuple(reasons))


def _sentiment_score(score_input: ScoreInput, missing: list[str]) -> ComponentScore:
    score = 0.0
    reasons: list[str] = []
    if score_input.limit_up_streak is None:
        missing.append("limit_up_streak")
    elif score_input.limit_up_streak >= 1:
        score += 5.0
        reasons.append("Limit-up streak shows positive momentum.")
    score += _bool_points(score_input.dragon_tiger_positive, "dragon_tiger_positive", 5.0, missing, reasons)
    if score_input.negative_event_count is None:
        missing.append("negative_event_count")
    elif score_input.negative_event_count == 0:
        score += 5.0
        reasons.append("No negative event was provided.")
    return ComponentScore("sentiment", score, 15.0, tuple(reasons))


def _bool_points(
    value: bool | None,
    field_name: str,
    points: float,
    missing: list[str],
    reasons: list[str],
) -> float:
    if value is None:
        missing.append(field_name)
        return 0.0
    if value:
        reasons.append(f"{field_name} is positive.")
        return points
    return 0.0
```

Modify `src/fintech_quant/features/__init__.py`:

```python
from fintech_quant.features.factors import (
    ComponentScore,
    ScoreInput,
    StockScore,
    factor_pipeline_name,
    score_stock,
)

__all__ = [
    "ComponentScore",
    "ScoreInput",
    "StockScore",
    "factor_pipeline_name",
    "score_stock",
]
```

- [ ] **Step 4: Run scoring tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_scoring_pipeline
```

Expected: PASS.

- [ ] **Step 5: Run full tests**

Run:

```bash
.venv/bin/python -m unittest discover -s tests
```

Expected: PASS.

- [ ] **Step 6: Commit and push**

Run:

```bash
git add src/fintech_quant/features tests/test_scoring_pipeline.py
git commit -m "feat: add stock scoring pipeline"
git push origin main
```

Expected: commit succeeds and push updates `origin/main`.

Change report:

```text
Changed files: feature scoring pipeline and tests.
Behavior added: transparent 35/25/25/15 scoring, component reasons, missing-data confidence.
Verification: .venv/bin/python -m unittest discover -s tests
Known limitations: scoring thresholds are first-pass deterministic rules, not optimized weights.
```

---

### Task 6: Score-Based Baseline Strategy and Vertical Flow

**Files:**
- Create: `src/fintech_quant/strategies/scored_baseline.py`
- Modify: `src/fintech_quant/strategies/__init__.py`
- Test: `tests/test_scored_baseline_strategy.py`

**Interfaces:**
- Consumes: `StockScore` from Task 5.
- Consumes: `RiskAction` from Task 4.
- Produces: `ScoredBaselineStrategy(name: str = "scored_baseline_v0", buy_threshold: float = 70.0)`.
- Produces: `ScoredBaselineStrategy.decide(state: dict[str, object]) -> TradeDecision`.

- [ ] **Step 1: Write the failing baseline strategy tests**

Create `tests/test_scored_baseline_strategy.py`:

```python
from __future__ import annotations

import unittest


class ScoredBaselineStrategyTest(unittest.TestCase):
    def test_buys_when_score_is_high_and_risk_allows(self) -> None:
        from fintech_quant.features import ScoreInput, score_stock
        from fintech_quant.risk import RiskAction
        from fintech_quant.strategies.scored_baseline import ScoredBaselineStrategy
        from fintech_quant.trading import TradeAction

        strategy = ScoredBaselineStrategy(buy_threshold=70.0)
        decision = strategy.decide(
            {
                "score": score_stock(
                    ScoreInput(
                        symbol="000001",
                        pe=18,
                        pb=1.5,
                        roe=0.16,
                        growth=0.12,
                        close_above_ma20=True,
                        close_above_ma60=True,
                        rsi=55,
                        macd_positive=True,
                        volume_confirmed=True,
                        main_net_inflow=1,
                        main_outflow_days=0,
                        margin_financing_positive=True,
                        limit_up_streak=1,
                        dragon_tiger_positive=True,
                        negative_event_count=0,
                    )
                ),
                "risk_action": RiskAction.NONE,
            }
        )

        self.assertEqual(decision.action, TradeAction.BUY)
        self.assertGreater(decision.confidence, 0.0)

    def test_risk_reduce_overrides_high_score(self) -> None:
        from fintech_quant.features import ScoreInput, score_stock
        from fintech_quant.risk import RiskAction
        from fintech_quant.strategies.scored_baseline import ScoredBaselineStrategy
        from fintech_quant.trading import TradeAction

        strategy = ScoredBaselineStrategy(buy_threshold=70.0)
        score = score_stock(
            ScoreInput(
                symbol="000001",
                pe=18,
                pb=1.5,
                roe=0.16,
                growth=0.12,
                close_above_ma20=True,
                close_above_ma60=True,
                rsi=55,
                macd_positive=True,
                volume_confirmed=True,
                main_net_inflow=1,
                main_outflow_days=0,
                margin_financing_positive=True,
                limit_up_streak=1,
                dragon_tiger_positive=True,
                negative_event_count=0,
            )
        )

        decision = strategy.decide({"score": score, "risk_action": RiskAction.REDUCE})

        self.assertEqual(decision.action, TradeAction.SELL)
        self.assertIn("risk", decision.reason.lower())

    def test_holds_when_score_is_below_threshold(self) -> None:
        from fintech_quant.features import ScoreInput, score_stock
        from fintech_quant.risk import RiskAction
        from fintech_quant.strategies.scored_baseline import ScoredBaselineStrategy
        from fintech_quant.trading import TradeAction

        strategy = ScoredBaselineStrategy(buy_threshold=70.0)
        decision = strategy.decide(
            {
                "score": score_stock(ScoreInput(symbol="000001")),
                "risk_action": RiskAction.NONE,
            }
        )

        self.assertEqual(decision.action, TradeAction.HOLD)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_scored_baseline_strategy
```

Expected: FAIL with `ModuleNotFoundError` for `fintech_quant.strategies.scored_baseline`.

- [ ] **Step 3: Implement score-based baseline strategy**

Create `src/fintech_quant/strategies/scored_baseline.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fintech_quant.features import StockScore
from fintech_quant.risk import RiskAction
from fintech_quant.strategies.base import Strategy
from fintech_quant.trading import TradeAction, TradeDecision


@dataclass(frozen=True)
class ScoredBaselineStrategy(Strategy):
    name: str = "scored_baseline_v0"
    buy_threshold: float = 70.0

    def decide(self, state: dict[str, Any]) -> TradeDecision:
        score = state["score"]
        risk_action = state.get("risk_action", RiskAction.NONE)
        if not isinstance(score, StockScore):
            raise TypeError("state['score'] must be a StockScore")
        if not isinstance(risk_action, RiskAction):
            raise TypeError("state['risk_action'] must be a RiskAction")

        if risk_action in {RiskAction.REDUCE, RiskAction.LIQUIDATE}:
            return TradeDecision(
                action=TradeAction.SELL,
                confidence=1.0,
                reason=f"Risk action {risk_action.value} overrides score {score.total}.",
            )
        if score.total >= self.buy_threshold:
            return TradeDecision(
                action=TradeAction.BUY,
                confidence=score.confidence,
                reason=f"Score {score.total} is above buy threshold {self.buy_threshold}.",
            )
        return TradeDecision(
            action=TradeAction.HOLD,
            confidence=score.confidence,
            reason=f"Score {score.total} is below buy threshold {self.buy_threshold}.",
        )
```

Modify `src/fintech_quant/strategies/__init__.py`:

```python
from fintech_quant.strategies.baseline import HoldStrategy
from fintech_quant.strategies.rl import RlBuySellHoldStrategy
from fintech_quant.strategies.scored_baseline import ScoredBaselineStrategy

__all__ = [
    "HoldStrategy",
    "RlBuySellHoldStrategy",
    "ScoredBaselineStrategy",
]
```

- [ ] **Step 4: Run baseline strategy tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_scored_baseline_strategy
```

Expected: PASS.

- [ ] **Step 5: Run full tests**

Run:

```bash
.venv/bin/python -m unittest discover -s tests
```

Expected: PASS.

- [ ] **Step 6: Commit and push**

Run:

```bash
git add src/fintech_quant/strategies tests/test_scored_baseline_strategy.py
git commit -m "feat: add scored baseline strategy"
git push origin main
```

Expected: commit succeeds and push updates `origin/main`.

Change report:

```text
Changed files: scored baseline strategy and tests.
Behavior added: buy/hold/sell logic that respects risk actions before score thresholds.
Verification: .venv/bin/python -m unittest discover -s tests
Known limitations: this is a decision policy only; portfolio sizing and full execution accounting remain separate.
```

---

### Task 7: Integration Contract and Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Test: `tests/test_phase_one_flow.py`

**Interfaces:**
- Consumes: Task 1 through Task 6 public interfaces.
- Produces: a deterministic fixture-backed flow proving normalized records, information retention, scoring, risk, drawdown, and baseline decision can work together.

- [ ] **Step 1: Write the failing integration flow test**

Create `tests/test_phase_one_flow.py`:

```python
from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path


class PhaseOneFlowTest(unittest.TestCase):
    def test_fixture_backed_research_flow_reaches_baseline_decision(self) -> None:
        from fintech_quant.backtesting import EquityPoint, calculate_drawdown
        from fintech_quant.features import ScoreInput, score_stock
        from fintech_quant.information import InformationCategory, InformationRecord, InformationRepository
        from fintech_quant.risk import RiskAction, RiskInput, evaluate_risk
        from fintech_quant.strategies.scored_baseline import ScoredBaselineStrategy
        from fintech_quant.trading import TradeAction

        with tempfile.TemporaryDirectory() as tmp:
            repo = InformationRepository(Path(tmp) / "info.jsonl")
            repo.append(
                InformationRecord(
                    symbol="000001",
                    sector="bank",
                    published_at=date(2026, 1, 2),
                    source="exchange",
                    category=InformationCategory.FINANCIAL_REPORT,
                    title="Recent report",
                    url="https://example.test/report",
                    summary="Revenue and ROE improved.",
                    risk_tags=(),
                )
            )

            score = score_stock(
                ScoreInput(
                    symbol="000001",
                    pe=18,
                    pb=1.5,
                    roe=0.16,
                    growth=0.12,
                    close_above_ma20=True,
                    close_above_ma60=True,
                    rsi=55,
                    macd_positive=True,
                    volume_confirmed=True,
                    main_net_inflow=1,
                    main_outflow_days=0,
                    margin_financing_positive=True,
                    limit_up_streak=1,
                    dragon_tiger_positive=True,
                    negative_event_count=len([record for record in repo.query(symbol="000001") if "negative_announcement" in record.risk_tags]),
                )
            )
            risk = evaluate_risk(RiskInput(portfolio_drawdown=0.02))
            drawdown = calculate_drawdown(
                [
                    EquityPoint(date(2026, 1, 1), 100.0),
                    EquityPoint(date(2026, 1, 2), 108.0),
                    EquityPoint(date(2026, 1, 3), 106.0),
                ]
            )
            decision = ScoredBaselineStrategy().decide({"score": score, "risk_action": risk.action})

            self.assertEqual(len(repo.query(symbol="000001")), 1)
            self.assertEqual(risk.action, RiskAction.NONE)
            self.assertLess(drawdown.max_drawdown, 0.15)
            self.assertEqual(decision.action, TradeAction.BUY)
```

- [ ] **Step 2: Run integration test**

Run:

```bash
.venv/bin/python -m unittest tests.test_phase_one_flow
```

Expected: PASS if Tasks 1 through 6 are complete.

- [ ] **Step 3: Update README and architecture notes**

Modify `README.md` by adding this section after `Current Scope`:

````markdown
## Phase 1 Research Loop

The first working slice is a daily A-share research loop:

```text
data providers -> information repository -> scoring -> risk warnings -> drawdown -> scored baseline strategy
```

AkShare is the default A-share provider. Tushare has a token-aware adapter for future account setup. The information repository has two retention classes: text financial/report records keep the most recent 3 years, while selected-universe stock data is retained for RL training material.
````

Modify `docs/architecture.md` by adding this section after `Core Flow`:

```markdown
## Phase 1 Module Contracts

- `data`: normalize A-share symbols and daily bars; route `source="auto"` to AkShare.
- `information`: persist classified text and selected-universe stock data records with distinct retention rules.
- `features`: produce 35/25/25/15 stock scores with component reasons and missing-data confidence.
- `risk`: evaluate portfolio, stock-specific, market, and systemic risk warnings.
- `backtesting`: calculate drawdown from dated equity points independently of strategy.
- `strategies`: provide a scored baseline decision policy for future DQN comparison.
```

- [ ] **Step 4: Run full tests**

Run:

```bash
.venv/bin/python -m unittest discover -s tests
```

Expected: PASS.

- [ ] **Step 5: Commit and push**

Run:

```bash
git add README.md docs/architecture.md tests/test_phase_one_flow.py
git commit -m "docs: describe phase one research loop"
git push origin main
```

Expected: commit succeeds and push updates `origin/main`.

Change report:

```text
Changed files: README, architecture notes, phase-one integration test.
Behavior added: documented research loop and deterministic end-to-end contract.
Verification: .venv/bin/python -m unittest discover -s tests
Known limitations: integration flow is fixture-backed; live data smoke tests are intentionally separate.
```

---

## Final Verification

After Task 7, run:

```bash
git status --short
.venv/bin/python -m unittest discover -s tests
git log --oneline -8
```

Expected:

- `git status --short` prints no tracked or untracked implementation changes.
- all unit tests pass;
- recent Git log shows one commit per completed phase plus the implementation-plan commit.

Do not mark the full user goal complete after this plan alone. The goal remains incomplete until the implementation tasks are executed, verified, committed, and backed up to GitHub.
