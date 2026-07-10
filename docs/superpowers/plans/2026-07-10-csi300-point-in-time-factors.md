# CSI 300 Point-in-Time Factors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible five-year CSI 300 research path using historical membership, point-in-time fundamental and capital-flow factors, fail-closed data health checks, and next-session A-share execution.

**Architecture:** Preserve every provider response under a versioned raw run, normalize it into explicit membership and factor tables, then use indexed as-of joins to build scores without future leakage. Formal CSI 300 runs pass through a data-health gate before baseline, risk-controlled baseline, RL dataset, target generation, or paper execution.

**Tech Stack:** Python 3.14, standard library dataclasses/csv/json/hashlib/bisect, AkShare, pytest.

## Global Constraints

- AkShare remains the primary provider; the normalized schema must not depend on AkShare field names outside adapter code.
- Historical CSI 300 membership is mandatory and must contain exactly 300 active members per research trading day.
- Raw provider responses are immutable; every retry uses a new run id or a new per-symbol attempt file.
- Financial visibility uses a verified public `available_date`, never only `report_period`.
- Data available after day D close can execute no earlier than the next trading session.
- Required groups fail closed when missing, all-zero, constant, stale, or below coverage thresholds.
- Formal runs keep the scored 35/25/25/15 baseline as the selection engine and keep DQN as an overlay only.
- Do not lower the 70 buy threshold or 0.8 confidence gate to manufacture trades.
- Strategy success requires positive net excess return versus CSI 300 and maximum drawdown no worse than 10%; software changes cannot guarantee this outcome.
- Live brokerage integration remains out of scope until at least eight consecutive paper-trading weeks pass every validation gate.

---

## File Structure

- `src/fintech_quant/data/historical_universe.py`: reconstruct and query membership intervals from an official anchor snapshot and dated adjustment events.
- `src/fintech_quant/data/run_artifacts.py`: create immutable run directories, hash files, and write raw/processed manifests.
- `src/fintech_quant/data/factor_store.py`: normalize information records into versioned fundamental and capital-flow CSV contracts.
- `src/fintech_quant/research/point_in_time.py`: indexed as-of lookup for supplemental factors.
- `src/fintech_quant/research/data_health.py`: calculate coverage, variation, staleness, membership, and leakage checks.
- `src/fintech_quant/backtesting/costs.py`: A-share commission and sell-side stamp-duty calculation.
- `scripts/build_historical_index_membership.py`: build membership intervals from source-backed CSV inputs.
- `scripts/collect_point_in_time_factors.py`: resumable per-symbol AkShare collection into an immutable raw run.
- `scripts/build_point_in_time_factors.py`: materialize normalized factor tables and the processed manifest.
- `scripts/validate_research_data.py`: write `data_health.json` and fail with a non-zero exit status when required gates fail.
- `scripts/run_csi300_research.py`: orchestrate the formal versioned CSI 300 research path.

---

### Task 1: Historical CSI 300 Membership Contract

**Files:**
- Create: `src/fintech_quant/data/historical_universe.py`
- Create: `scripts/build_historical_index_membership.py`
- Create: `tests/test_historical_universe.py`
- Create: `tests/test_build_historical_index_membership_script.py`
- Modify: `src/fintech_quant/data/__init__.py`

**Interfaces:**
- Consumes: an official anchor snapshot with `symbol,as_of,source` and adjustment rows with `effective_date,removed_symbol,added_symbol,source_url`.
- Produces: `MembershipInterval`, `MembershipAdjustment`, `build_membership_intervals(...)`, `active_symbols(...)`, and `write_membership_csv(...)`.

- [ ] **Step 1: Write failing membership reconstruction tests**

```python
def test_reconstructs_membership_backward_without_seeing_future_addition():
    anchor = MembershipAnchor(
        index_code="000300",
        as_of=date(2026, 6, 15),
        symbols=("000001.SZ", "600000.SH", "600519.SH"),
        source="csindex",
    )
    changes = [
        MembershipAdjustment(
            effective_date=date(2026, 6, 15),
            removed_symbol="000002.SZ",
            added_symbol="600519.SH",
            source_url="https://official.example/adjustment.pdf",
        )
    ]
    intervals = build_membership_intervals(
        anchor,
        changes,
        start=date(2026, 6, 1),
        expected_members=3,
    )
    assert active_symbols(intervals, date(2026, 6, 14)) == (
        "000001.SZ", "000002.SZ", "600000.SH"
    )
    assert active_symbols(intervals, date(2026, 6, 15)) == (
        "000001.SZ", "600000.SH", "600519.SH"
    )


def test_reconstruction_rejects_incomplete_adjustment_pair():
    with pytest.raises(ValueError, match="removed symbol is not active"):
        build_membership_intervals(anchor, bad_changes, start=date(2026, 1, 1), expected_members=3)
```

- [ ] **Step 2: Run tests and confirm the missing module failure**

Run: `.venv/bin/python -m pytest tests/test_historical_universe.py -q`

Expected: FAIL with `ModuleNotFoundError: fintech_quant.data.historical_universe`.

- [ ] **Step 3: Implement membership reconstruction and exact-count validation**

```python
@dataclass(frozen=True)
class MembershipAdjustment:
    effective_date: date
    removed_symbol: str
    added_symbol: str
    source_url: str


@dataclass(frozen=True)
class MembershipInterval:
    index_code: str
    symbol: str
    member_from: date
    member_to: date | None
    source: str
    source_fetched_at: str


def active_symbols(intervals: Sequence[MembershipInterval], on_date: date) -> tuple[str, ...]:
    return tuple(sorted(
        row.symbol
        for row in intervals
        if row.member_from <= on_date and (row.member_to is None or on_date < row.member_to)
    ))
```

`build_membership_intervals` must group changes by effective date, walk backward from the anchor, invert each add/remove pair, assert the active count after every boundary, and compress identical active periods into per-symbol intervals.

- [ ] **Step 4: Add the CSV CLI and fixture test**

```python
completed = subprocess.run([
    sys.executable,
    "scripts/build_historical_index_membership.py",
    "--anchor", str(anchor_path),
    "--adjustments", str(adjustments_path),
    "--index-code", "000300",
    "--start", "2026-06-01",
    "--expected-members", "3",
    "--output", str(output_path),
], cwd=repo_root, capture_output=True, text=True)
assert completed.returncode == 0
assert rows[0].keys() == {
    "index_code", "symbol", "member_from", "member_to", "source", "source_fetched_at"
}
```

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/python -m pytest tests/test_historical_universe.py tests/test_build_historical_index_membership_script.py -q`

Expected: all tests pass.

```bash
git add src/fintech_quant/data/historical_universe.py src/fintech_quant/data/__init__.py scripts/build_historical_index_membership.py tests/test_historical_universe.py tests/test_build_historical_index_membership_script.py
git commit -m "feat: add historical CSI membership contract"
```

---

### Task 2: Verified Financial Availability Dates

**Files:**
- Modify: `src/fintech_quant/information/fetchers.py`
- Modify: `tests/test_information_repository.py`

**Interfaces:**
- Consumes: AkShare valuation, financial-indicator, and Sina financial-statement rows.
- Produces: information records whose metadata separates `record_kind`, `report_period`, and `available_date_source`; financial statements use `更新日期` as `published_at`.

- [ ] **Step 1: Add failing disclosure-date tests**

```python
def test_financial_statement_uses_update_date_as_public_availability():
    row = {
        "报告日": "20230331",
        "更新日期": "2023-04-24 T18:05:05",
        "商誉": "100",
        "资产总计": "1000",
    }
    record = AkShareFinancialStatementFetcher(
        statement_types=("资产负债表",),
        fetcher=lambda stock, statement: [row],
    ).fetch("600600", None, date(2023, 1, 1), date(2023, 6, 30))[0]
    assert record.published_at == date(2023, 4, 24)
    assert record.metadata["report_period"] == "2023-03-31"
    assert record.metadata["available_date_source"] == "更新日期"


def test_financial_statement_without_update_date_fails_closed():
    with pytest.raises(ProviderFetchError, match="financial-statement fetch failed"):
        fetcher_without_update_date.fetch("600600", None, start, end)
```

- [ ] **Step 2: Run the targeted tests and confirm they fail on report-date behavior**

Run: `.venv/bin/python -m pytest tests/test_information_repository.py -k 'update_date or financial_statement_without' -q`

Expected: FAIL because `published_at` equals the report period or the missing update date is accepted.

- [ ] **Step 3: Implement strict date parsing and metadata**

```python
def _available_date_from_statement(row: Mapping[str, object]) -> date:
    raw = _first_value(row, "更新日期", "公告日期", "available_date")
    return date.fromisoformat(str(raw).strip().split("T", 1)[0].split(" ", 1)[0])


def _record_from_financial_statement_row(row, normalized_symbol, statement_type):
    report_period = _parse_date(_first_value(row, "报告日", "报表日期", "截止日期", "report_date"))
    available_date = _available_date_from_statement(row)
    return InformationRecord(
        symbol=normalized_symbol,
        sector=None,
        published_at=available_date,
        source="akshare_financial_statement",
        category=InformationCategory.STOCK_DATA,
        title=f"{normalized_symbol} {statement_type} {report_period.isoformat()}",
        url="",
        summary=_financial_statement_summary(row),
        risk_tags=("selected_universe", "financial_statement", _statement_tag(statement_type)),
        metadata={
            "statement_type": statement_type,
            "report_period": report_period.isoformat(),
            "available_date_source": "更新日期" if row.get("更新日期") else "公告日期",
            "raw_row": _metadata_row(row),
        },
    )
```

Fundamental valuation records must set `record_kind="valuation"`; financial-indicator records must set `record_kind="financial_indicator"` and carry `report_period`. Their report period alone is never treated as public availability.

- [ ] **Step 4: Run repository and fetcher regression tests**

Run: `.venv/bin/python -m pytest tests/test_information_repository.py tests/test_research_dataset_phase4.py -q`

Expected: all tests pass after updating old assertions from report date to verified update date.

- [ ] **Step 5: Commit**

```bash
git add src/fintech_quant/information/fetchers.py tests/test_information_repository.py tests/test_research_dataset_phase4.py
git commit -m "fix: use verified financial availability dates"
```

---

### Task 3: Immutable Run Artifacts and Resumable Factor Collection

**Files:**
- Create: `src/fintech_quant/data/run_artifacts.py`
- Create: `scripts/collect_point_in_time_factors.py`
- Create: `tests/test_run_artifacts.py`
- Create: `tests/test_collect_point_in_time_factors_script.py`

**Interfaces:**
- Consumes: run id, historical membership union, date range, provider fetchers, and an optional parent run.
- Produces: `RunArtifactStore`, per-symbol immutable JSONL files, `collection_state.json`, and `manifest.json` with hashes and failures.

- [ ] **Step 1: Write failing immutability and resume tests**

```python
def test_store_refuses_to_overwrite_raw_artifact(tmp_path):
    store = RunArtifactStore(tmp_path, "run-1", layer="raw")
    store.write_jsonl("fundamentals/000001.SZ.jsonl", [{"value": 1}])
    with pytest.raises(FileExistsError):
        store.write_jsonl("fundamentals/000001.SZ.jsonl", [{"value": 2}])


def test_collector_resume_skips_completed_symbol(tmp_path):
    first = run_fixture_collection(tmp_path, fail_symbol="600000.SH")
    second = run_fixture_collection(tmp_path, resume_from=first.run_dir)
    assert second.fetch_counts["000001.SZ"] == 0
    assert second.fetch_counts["600000.SH"] == 1
```

- [ ] **Step 2: Verify the tests fail because run artifact APIs do not exist**

Run: `.venv/bin/python -m pytest tests/test_run_artifacts.py tests/test_collect_point_in_time_factors_script.py -q`

Expected: FAIL with missing module/script errors.

- [ ] **Step 3: Implement manifest hashing and atomic metadata writes**

```python
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RunArtifactStore:
    def write_jsonl(self, relative_path: str, rows: Iterable[Mapping[str, object]]) -> Path:
        path = self.run_dir / relative_path
        if path.exists():
            raise FileExistsError(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")
        self._artifacts.append(artifact_metadata(path, self.run_dir))
        return path
```

The manifest must include run id, layer, parent run, request dates, union symbols, provider endpoints, AkShare/Python versions, Git SHA, artifact hashes, row counts, success/empty/failure status, and exception messages.

- [ ] **Step 4: Implement the resumable collector CLI**

The CLI accepts `--source fixture|akshare`, `--membership`, `--start`, `--end`, `--run-id`, `--raw-root`, and `--resume-from`. It calls the existing `AkShareFundamentalFetcher`, `AkShareFinancialStatementFetcher`, and `AkShareFundFlowFetcher` per union symbol and persists each source separately. A failed symbol is recorded and does not erase successful raw files.

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/python -m pytest tests/test_run_artifacts.py tests/test_collect_point_in_time_factors_script.py -q`

Expected: all tests pass.

```bash
git add src/fintech_quant/data/run_artifacts.py scripts/collect_point_in_time_factors.py tests/test_run_artifacts.py tests/test_collect_point_in_time_factors_script.py
git commit -m "feat: add immutable resumable factor collection"
```

---

### Task 4: Versioned Fundamental and Capital-Flow Tables

**Files:**
- Create: `src/fintech_quant/data/factor_store.py`
- Create: `scripts/build_point_in_time_factors.py`
- Create: `tests/test_factor_store.py`
- Create: `tests/test_build_point_in_time_factors_script.py`

**Interfaces:**
- Consumes: raw run manifest and source JSONL artifacts from Task 3.
- Produces: `FundamentalSnapshot`, `CapitalFlowSnapshot`, `materialize_fundamentals(...)`, `materialize_capital_flow(...)`, normalized CSV files, and a processed manifest referencing raw hashes.

- [ ] **Step 1: Write failing materialization tests**

```python
def test_financial_indicator_uses_matching_statement_availability():
    rows = materialize_fundamentals([
        financial_indicator_record(
            report_period="2023-03-31", roe=0.16, growth=0.12,
        ),
        statement_record(
            report_period="2023-03-31", available_date="2023-04-24",
        ),
        valuation_record(available_date="2023-04-24", pe=18.0, pb=1.5),
    ])
    assert rows[-1].available_date == date(2023, 4, 24)
    assert rows[-1].values == {"pe": 18.0, "pb": 1.5, "roe": 0.16, "growth": 0.12}


def test_unmatched_financial_indicator_is_not_materialized():
    assert materialize_fundamentals([financial_indicator_record(report_period="2023-03-31")]) == []


def test_missing_flow_day_does_not_reset_outflow_streak():
    rows = materialize_capital_flow([
        flow_record("2026-01-02", -10.0),
        flow_record("2026-01-06", -20.0),
    ], trading_dates=[date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 6)])
    assert rows[-1].values["main_outflow_days"] is None
```

- [ ] **Step 2: Verify the new tests fail**

Run: `.venv/bin/python -m pytest tests/test_factor_store.py -q`

Expected: FAIL with missing factor store APIs.

- [ ] **Step 3: Implement deterministic snapshot materialization**

```python
@dataclass(frozen=True)
class FundamentalSnapshot:
    symbol: str
    report_period: date | None
    available_date: date
    source: str
    source_fetched_at: str
    values: dict[str, float | None]


@dataclass(frozen=True)
class CapitalFlowSnapshot:
    symbol: str
    trade_date: date
    available_date: date
    source: str
    source_fetched_at: str
    values: dict[str, float | int | bool | None]
```

Materialization must sort by `(symbol, available_date, source)`, join financial indicators to statement availability by `(symbol, report_period)`, carry the latest disclosed financial values into valuation snapshots, and never zero-fill missing fields.

- [ ] **Step 4: Add the processed-run CLI and manifest assertions**

```python
completed = run_build_cli(raw_manifest, processed_root, run_id="processed-1")
manifest = json.loads((processed_root / "processed-1/manifest.json").read_text())
assert completed.returncode == 0
assert manifest["parent_manifest_sha256"] == sha256_file(raw_manifest)
assert manifest["artifacts"]["fundamentals.csv"]["row_count"] > 0
assert manifest["artifacts"]["capital_flow.csv"]["row_count"] > 0
```

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/python -m pytest tests/test_factor_store.py tests/test_build_point_in_time_factors_script.py -q`

Expected: all tests pass.

```bash
git add src/fintech_quant/data/factor_store.py scripts/build_point_in_time_factors.py tests/test_factor_store.py tests/test_build_point_in_time_factors_script.py
git commit -m "feat: materialize point-in-time factor tables"
```

---

### Task 5: Indexed As-Of Joins and Historical-Membership Filtering

**Files:**
- Create: `src/fintech_quant/research/point_in_time.py`
- Modify: `src/fintech_quant/research/dataset.py`
- Modify: `src/fintech_quant/research/scoring.py`
- Modify: `src/fintech_quant/research/run.py`
- Modify: `tests/test_research_dataset_phase4.py`
- Modify: `tests/test_research_scoring.py`
- Modify: `tests/test_research_run.py`

**Interfaces:**
- Consumes: normalized factor tables and membership intervals.
- Produces: `SupplementalAsOfIndex`, `lookup(symbol, signal_date, max_age_days)`, `membership_path` and `require_point_in_time` dataset options.

- [ ] **Step 1: Write future-leakage and membership-boundary tests**

```python
def test_as_of_lookup_never_uses_future_disclosure():
    index = SupplementalAsOfIndex([
        supplemental("000001.SZ", "2026-04-24", pe=18.0),
        supplemental("000001.SZ", "2026-08-20", pe=1.0),
    ])
    assert index.lookup("000001.SZ", date(2026, 6, 30), max_age_days=180).values["pe"] == 18.0


def test_dataset_excludes_member_before_effective_date(tmp_path):
    dataset = load_research_dataset(
        features_path,
        universe_path,
        membership_path=membership_path,
        require_point_in_time=True,
    )
    assert (date(2026, 6, 14), "600519.SH") not in {
        (row.trade_date, row.symbol) for row in dataset.features
    }
    assert (date(2026, 6, 15), "600519.SH") in {
        (row.trade_date, row.symbol) for row in dataset.features
    }
```

- [ ] **Step 2: Run the tests and confirm current exact-date matching fails**

Run: `.venv/bin/python -m pytest tests/test_research_dataset_phase4.py tests/test_research_scoring.py -k 'as_of or effective_date or future_disclosure' -q`

Expected: FAIL because the APIs are absent or the future/previous snapshot behavior is wrong.

- [ ] **Step 3: Implement a bisect-backed point-in-time index**

```python
class SupplementalAsOfIndex:
    def __init__(self, rows: Iterable[SupplementalRow]) -> None:
        grouped: dict[str, list[SupplementalRow]] = {}
        for row in rows:
            if row.trade_date is None:
                continue
            grouped.setdefault(row.symbol, []).append(row)
        self._rows = {symbol: tuple(sorted(items, key=lambda item: item.trade_date)) for symbol, items in grouped.items()}
        self._dates = {symbol: tuple(item.trade_date for item in items) for symbol, items in self._rows.items()}

    def lookup(self, symbol: str, signal_date: date, max_age_days: int | None = None) -> SupplementalRow | None:
        dates = self._dates.get(symbol, ())
        position = bisect_right(dates, signal_date) - 1
        if position < 0:
            return None
        row = self._rows[symbol][position]
        if max_age_days is not None and (signal_date - row.trade_date).days > max_age_days:
            return None
        return row
```

Formal runs reject undated supplemental rows. Existing undated rows remain accepted only when `require_point_in_time=False` so legacy fixtures do not silently enter CSI 300 runs.

- [ ] **Step 4: Use one index per dataset in scoring and risk construction**

Build the fundamental and flow indexes once at the start of `build_stock_scores` and `_build_static_risk_inputs`; do not scan all snapshots for every feature row. Use a 180-calendar-day fundamental age and a trading-calendar-aware three-session capital-flow age.

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/python -m pytest tests/test_research_dataset_phase4.py tests/test_research_scoring.py tests/test_research_run.py -q`

Expected: all tests pass.

```bash
git add src/fintech_quant/research/point_in_time.py src/fintech_quant/research/dataset.py src/fintech_quant/research/scoring.py src/fintech_quant/research/run.py tests/test_research_dataset_phase4.py tests/test_research_scoring.py tests/test_research_run.py
git commit -m "feat: enforce point-in-time factor joins"
```

---

### Task 6: Fail-Closed Data Health Gate

**Files:**
- Create: `src/fintech_quant/research/data_health.py`
- Create: `scripts/validate_research_data.py`
- Create: `tests/test_research_data_health.py`
- Create: `tests/test_validate_research_data_script.py`
- Modify: `src/fintech_quant/research/__init__.py`

**Interfaces:**
- Consumes: `ResearchDataset`, stock scores, membership intervals, and `DataHealthThresholds`.
- Produces: `DataHealthReport`, `DataHealthIssue`, `validate_research_data(...)`, JSON output, and exit code 2 on a failed required gate.

- [ ] **Step 1: Write one failing test per required gate**

```python
@pytest.mark.parametrize("broken_fixture,expected_code", [
    ("missing_members", "membership_count"),
    ("low_price_coverage", "price_coverage"),
    ("constant_fundamental", "fundamental_constant"),
    ("zero_capital_flow", "capital_flow_all_zero"),
    ("stale_fundamental", "fundamental_stale"),
    ("future_available_date", "future_leakage"),
])
def test_required_health_failures(broken_fixture, expected_code):
    report = validate_research_data(make_dataset(broken_fixture), thresholds=fixture_thresholds())
    assert report.passed is False
    assert expected_code in {issue.code for issue in report.issues}
```

- [ ] **Step 2: Run and confirm the health module is missing**

Run: `.venv/bin/python -m pytest tests/test_research_data_health.py -q`

Expected: FAIL with missing module errors.

- [ ] **Step 3: Implement explicit production thresholds and metrics**

```python
@dataclass(frozen=True)
class DataHealthThresholds:
    expected_members: int = 300
    minimum_price_coverage: float = 0.95
    minimum_fundamental_coverage: float = 0.80
    minimum_capital_flow_coverage: float = 0.95
    fundamental_warmup_days: int = 180
    maximum_fundamental_age_days: int = 180
    maximum_capital_flow_age_sessions: int = 3


@dataclass(frozen=True)
class DataHealthReport:
    passed: bool
    metrics: dict[str, object]
    issues: tuple[DataHealthIssue, ...]
```

Report field coverage, group coverage, minimum/maximum, unique count, standard deviation, all-zero status, stale counts, future-date counts, per-day member counts, and per-source failures. Coverage success does not override a constant or all-zero failure.

- [ ] **Step 4: Add the CLI behavior test**

```python
completed = run_validate_cli(broken_paths, output_path)
payload = json.loads(output_path.read_text())
assert completed.returncode == 2
assert payload["passed"] is False
assert payload["issues"]
```

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/python -m pytest tests/test_research_data_health.py tests/test_validate_research_data_script.py -q`

Expected: all tests pass.

```bash
git add src/fintech_quant/research/data_health.py src/fintech_quant/research/__init__.py scripts/validate_research_data.py tests/test_research_data_health.py tests/test_validate_research_data_script.py
git commit -m "feat: fail closed on unhealthy research factors"
```

---

### Task 7: Next-Session Execution and A-Share Costs

**Files:**
- Create: `src/fintech_quant/backtesting/costs.py`
- Modify: `src/fintech_quant/backtesting/portfolio_research_runner.py`
- Modify: `src/fintech_quant/backtesting/__init__.py`
- Modify: `src/fintech_quant/research/run.py`
- Modify: `tests/test_portfolio_research_runner.py`
- Modify: `tests/test_research_run.py`

**Interfaces:**
- Consumes: signal-date scores, next-session bars, and `AShareCostModel`.
- Produces: trades with `signal_date`, execution-date prices, commission, stamp duty, and total cost; formal research defaults to one-session delay.

- [ ] **Step 1: Write failing execution-timing and cost tests**

```python
def test_signal_executes_on_next_session_not_same_close():
    bars = [_bar("000001.SZ", "2026-01-02", 10.0), _bar("000001.SZ", "2026-01-05", 11.0)]
    scores = {(date(2026, 1, 2), "000001.SZ"): _score("000001.SZ", 80.0)}
    result = run_portfolio_scored_baseline_backtest(bars, scores, initial_cash=100_000.0)
    assert result.trades[0].signal_date == date(2026, 1, 2)
    assert result.trades[0].trade_date == date(2026, 1, 5)
    assert result.trades[0].price == 11.0


def test_sell_cost_includes_date_appropriate_stamp_duty():
    model = AShareCostModel(commission_rate=0.0003, minimum_commission=5.0)
    cost = model.sell_cost(10_000.0, date(2023, 8, 28))
    assert cost.commission == 5.0
    assert cost.stamp_duty == 5.0
```

- [ ] **Step 2: Run and confirm current same-day execution fails**

Run: `.venv/bin/python -m pytest tests/test_portfolio_research_runner.py -k 'next_session or stamp_duty' -q`

Expected: FAIL because trades execute on the score date and no stamp-duty field exists.

- [ ] **Step 3: Implement the cost model**

```python
@dataclass(frozen=True)
class TradeCost:
    commission: float
    stamp_duty: float

    @property
    def total(self) -> float:
        return round(self.commission + self.stamp_duty, 6)


@dataclass(frozen=True)
class AShareCostModel:
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0

    def buy_cost(self, notional: float, trade_date: date) -> TradeCost:
        return TradeCost(max(self.minimum_commission, notional * self.commission_rate), 0.0)

    def sell_cost(self, notional: float, trade_date: date) -> TradeCost:
        stamp_rate = 0.0005 if trade_date >= date(2023, 8, 28) else 0.001
        return TradeCost(max(self.minimum_commission, notional * self.commission_rate), notional * stamp_rate)
```

- [ ] **Step 4: Queue decisions by symbol until the next available bar**

At each trading date, execute pending prior-session decisions first using the current bar and constraints, then create new pending decisions from current scores. Add `signal_date` and separate cost fields to `PortfolioBacktestTrade`. A missing, suspended, limit-up, or limit-down execution bar keeps or blocks the order according to the existing A-share constraint rules and records the reason.

- [ ] **Step 5: Update report serialization and regression tests**

Formal `ResearchRunConfig` defaults to one-session delay and the cost model above. Legacy zero-delay behavior may exist only behind an explicit test-only/research comparison option and must be recorded in the report configuration.

- [ ] **Step 6: Verify and commit**

Run: `.venv/bin/python -m pytest tests/test_portfolio_research_runner.py tests/test_research_run.py -q`

Expected: all tests pass.

```bash
git add src/fintech_quant/backtesting/costs.py src/fintech_quant/backtesting/portfolio_research_runner.py src/fintech_quant/backtesting/__init__.py src/fintech_quant/research/run.py tests/test_portfolio_research_runner.py tests/test_research_run.py
git commit -m "feat: execute signals on the next A-share session"
```

---

### Task 8: Formal CSI 300 Pipeline Integration

**Files:**
- Create: `scripts/run_csi300_research.py`
- Create: `tests/test_run_csi300_research_script.py`
- Modify: `scripts/build_rl_dataset.py`
- Modify: `scripts/summarize_scoring_coverage.py`
- Modify: `scripts/analyze_stock_scores.py`
- Modify: `scripts/run_research_baseline.py`
- Modify: `scripts/run_daily_research_pipeline.py`
- Modify: `tests/test_daily_research_pipeline_script.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: processed run manifest, membership, prices/features, factor tables, benchmark, information repository, and run id.
- Produces: health report, scoring coverage, stock analysis, baseline report, risk-controlled report, RL state dataset, benchmark comparison, and a top-level run manifest.

- [ ] **Step 1: Write a failing end-to-end CLI fixture test**

```python
completed = subprocess.run([
    sys.executable,
    "scripts/run_csi300_research.py",
    "--processed-manifest", str(processed_manifest),
    "--features", str(features_path),
    "--benchmark", str(benchmark_path),
    "--run-id", "fixture-csi300",
    "--expected-members", "3",
    "--output-root", str(output_root),
], cwd=repo_root, capture_output=True, text=True)
assert completed.returncode == 0, completed.stderr
assert (output_root / "fixture-csi300/data_health.json").exists()
assert (output_root / "fixture-csi300/baseline/run_report.json").exists()
assert (output_root / "fixture-csi300/risk_controlled/run_report.json").exists()
assert (output_root / "fixture-csi300/manifest.json").exists()
```

- [ ] **Step 2: Run and confirm the orchestrator is absent**

Run: `.venv/bin/python -m pytest tests/test_run_csi300_research_script.py -q`

Expected: FAIL because `run_csi300_research.py` does not exist.

- [ ] **Step 3: Thread point-in-time inputs through every downstream CLI**

Add `--membership`, `--fundamentals`, `--capital-flow`, `--data-health`, and `--require-point-in-time` where applicable. Every command must load the same processed manifest and refuse mismatched input hashes. Fix the duplicated `--daily-output` argument in `run_daily_research_pipeline.py` while touching that command construction.

- [ ] **Step 4: Implement fail-before-research orchestration**

```python
health = _run_json_command(validate_command, health_path)
if not health["passed"]:
    print(f"data_health={health_path}", file=sys.stderr)
    return 2
_run(baseline_command)
_run(risk_controlled_command)
_run(rl_dataset_command)
_run(comparison_command)
write_top_level_manifest(...)
```

The DQN overlay is included only when a separately supplied diagnostics report states that backend parity passed; otherwise the manifest records `dqn_overlay_status="diagnostic_only"`.

- [ ] **Step 5: Add README commands for fixture, 30-stock diagnostic, and full CSI 300 runs**

Document exact command order: build membership, collect raw factors, materialize factors, refresh prices/features, validate health, then run formal research. State that a failed strategy gate is a valid research result and not an engineering failure.

- [ ] **Step 6: Verify and commit**

Run: `.venv/bin/python -m pytest tests/test_run_csi300_research_script.py tests/test_daily_research_pipeline_script.py tests/test_run_research_baseline_script.py tests/test_rl_dataset.py -q`

Expected: all tests pass.

```bash
git add scripts/run_csi300_research.py scripts/build_rl_dataset.py scripts/summarize_scoring_coverage.py scripts/analyze_stock_scores.py scripts/run_research_baseline.py scripts/run_daily_research_pipeline.py tests/test_run_csi300_research_script.py tests/test_daily_research_pipeline_script.py README.md
git commit -m "feat: orchestrate formal CSI 300 research"
```

---

### Task 9: Reproducibility and Full-Chain Verification

**Files:**
- Create: `tests/test_csi300_reproducibility.py`
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: all Task 1-8 outputs.
- Produces: deterministic artifact hashes for the fixed fixture, a documented real-data command sequence, and an evidence-backed project-status update.

- [ ] **Step 1: Add a deterministic rerun test**

```python
def test_same_inputs_and_commit_produce_identical_processed_hashes(tmp_path):
    first = run_fixture_pipeline(tmp_path / "first", created_at="2026-07-10T12:00:00+08:00")
    second = run_fixture_pipeline(tmp_path / "second", created_at="2026-07-10T12:00:00+08:00")
    assert first.normalized_data_hashes == second.normalized_data_hashes
    assert first.score_hash == second.score_hash
```

Manifest file paths and run ids may differ; the test compares normalized data and score artifact hashes, not the full manifest bytes.

- [ ] **Step 2: Run the deterministic fixture twice**

Run: `.venv/bin/python -m pytest tests/test_csi300_reproducibility.py -q`

Expected: PASS with identical normalized-data and score hashes.

- [ ] **Step 3: Run all static and automated verification**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src scripts tests
uvx ruff check src/fintech_quant/data/historical_universe.py src/fintech_quant/data/run_artifacts.py src/fintech_quant/data/factor_store.py src/fintech_quant/research/point_in_time.py src/fintech_quant/research/data_health.py src/fintech_quant/backtesting/costs.py scripts/build_historical_index_membership.py scripts/collect_point_in_time_factors.py scripts/build_point_in_time_factors.py scripts/validate_research_data.py scripts/run_csi300_research.py
git diff --check origin/main...HEAD
```

Expected: pytest has zero failures, compileall exits 0, Ruff reports no errors in changed production files, and diff check is empty.

- [ ] **Step 4: Run the 30-stock diagnostic before the full CSI 300 fetch**

Use a new run id and immutable output paths. Confirm that fundamental and capital-flow component scores are non-constant, the score distribution can cross the unchanged entry gates, and the baseline creates economically meaningful target positions. If the health gate fails, preserve the report and fix the data path rather than tuning thresholds.

- [ ] **Step 5: Run the full historical CSI 300 research path**

Collect approximately five years for the historical-member union, resume provider failures, materialize and validate the factor tables, then execute `run_csi300_research.py`. Record engineering gate results separately from net excess return, 10% drawdown, and walk-forward strategy gates.

- [ ] **Step 6: Update project evidence and commit**

Update `AGENTS.md` only with results supported by generated manifests and reports. Do not call the strategy profitable when any required gate fails.

```bash
git add tests/test_csi300_reproducibility.py AGENTS.md
git commit -m "docs: record CSI 300 point-in-time validation"
git push origin codex/csi300-point-in-time-factors
```

---

## Plan Self-Review Result

- Spec coverage: historical membership, immutable inputs, point-in-time availability, factor materialization, health gates, next-session execution, costs, CSI 300 orchestration, reproducibility, and strategy reporting each map to a task.
- Deferred independent subsystems: the 8%/10% cross-backend drawdown parity, DQN backend selection, eight-week scheduler evidence, and live brokerage adapter require separate plans after this data/baseline plan passes its engineering gates.
- Interface consistency: membership uses interval rows throughout; supplemental factors use `available_date` as the existing `SupplementalRow.trade_date`; formal dataset loading requires dated rows; health validation precedes all downstream consumers.
- No automatic fallback to current constituents or undated fundamentals exists in the formal path.
