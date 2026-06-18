# A-Share Research System Phase 1 Design

## Context

The current project is a clean scaffold for an A-share daily quantitative
research system. It has module boundaries for data, features, strategies,
backtesting, risk, execution, training, and reports, but the core production
logic is still mostly placeholder code. The first phase should turn the scaffold
into a small, auditable research loop before investing more effort in DQN/RL.

The design borrows the useful architectural ideas from HKUDS/Vibe-Trading:

- route market data through a single loader interface instead of ad hoc scripts;
- keep data-source fallback explicit and testable;
- make research outputs reproducible and auditable;
- separate market research, risk gates, strategy decisions, and execution.

It does not copy HKUDS/Vibe-Trading's large agent/swarm architecture. That would
add operational complexity before this project has reliable A-share data,
baseline strategy comparison, drawdown accounting, and risk controls.

## Goals

Phase 1 builds a practical A-share research loop with these deliverables:

1. A unified A-share data access layer using AkShare first, with a Tushare
   adapter interface ready for a future token.
2. An information-surface repository populated by automatic fetch scripts for
   regulatory policy, company announcement or financial-report metadata, and
   sector or stock event records.
3. A transparent multi-dimensional stock analysis score:
   - fundamental: 35%;
   - technical: 25%;
   - capital flow: 25%;
   - sentiment/event: 15%.
4. A four-layer risk warning engine:
   - portfolio drawdown;
   - single-stock negative events;
   - broad-market abnormal moves;
   - systemic risk.
5. A drawdown engine that produces an equity curve, rolling peak, drawdown
   series, maximum drawdown, and risk actions such as forced liquidation.
6. A simple score-based baseline strategy that can later be compared with DQN.

## Non-Goals

Phase 1 does not implement live brokerage trading, intraday high-frequency
execution, a full MCP/Hermes server, or a complete DQN training upgrade.

The Hermes/MCP-style interface is deferred intentionally. For current daily
research usage, automatic fetch scripts plus a local information repository are
more reliable and easier to audit. Once the local data contracts are stable, the
same functions can be exposed through Hermes/MCP without changing the research
logic.

## Architecture

The first-stage flow is:

```text
A-share data providers
  -> normalized local records
  -> information repository
  -> factor and score pipeline
  -> risk warning engine
  -> drawdown engine
  -> baseline strategy / future RL state
  -> reportable output
```

Each module owns one responsibility:

- `fintech_quant.data`: provider adapters, symbol normalization, source
  registry, local record schema.
- `fintech_quant.information`: automatic fetch scripts, local information
  records, simple event and risk tags.
- `fintech_quant.features`: factor calculation and multi-dimensional scoring.
- `fintech_quant.risk`: risk limit definitions, warning rules, risk actions.
- `fintech_quant.backtesting`: drawdown and portfolio accounting primitives.
- `fintech_quant.strategies`: baseline decision logic and future RL policy
  integration.

## Data Layer

The data layer should expose a small stable interface:

```python
provider.history(symbol: str, start: date, end: date) -> list[dict[str, object]]
```

For Phase 1, rows are normalized to these fields when available:

- `symbol`
- `trade_date`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `amount`
- `source`

AkShare is the default provider. Tushare is represented by an adapter that
validates token configuration and raises a clear missing-token error until the
token is supplied. A provider registry supports `source="auto"` and can later
add fallback ordering.

Symbol normalization supports common A-share forms:

- `000001`
- `000001.SZ`
- `600000.SH`
- `688001.SH`

The first implementation should stay daily-first. Real-time tick and order-book
depth are out of scope for this phase.

## Information Repository

The information repository stores source-backed records under local data paths
that are not committed to Git. Each record keeps:

- `record_id`
- `symbol` or `sector`
- `published_at`
- `source`
- `category`
- `title`
- `url`
- `summary`
- `risk_tags`

The repository is split into two retention classes:

- text financial/report records: regulatory policy, company announcements,
  financial reports, sector events, and market sentiment text are retained for
  the most recent 3 years only;
- selected-universe stock data records: all normalized price, factor,
  capital-flow, risk, and score records for stocks that enter the selected
  research universe are retained without the 3-year pruning rule because they
  are training material for future RL state and reward design.

Initial categories:

- `regulatory_policy`
- `financial_report`
- `company_announcement`
- `sector_event`
- `market_sentiment`

Initial risk tags:

- `st_warning`
- `goodwill_high`
- `pledge_high`
- `negative_announcement`
- `policy_pressure`
- `major_capital_outflow`

The first fetcher can be a script-oriented interface rather than an always-on
service. It should support fetching by `symbol`, by `sector`, and by date range.
Fetched records are append-only by default and deduplicated by a stable key built
from source, URL or title, symbol or sector, and published date.

## Multi-Dimensional Analysis

The stock scoring pipeline produces a score from 0 to 100 plus component
breakdown and explanation strings.

Component weights:

- fundamental score: 35 points;
- technical score: 25 points;
- capital-flow score: 25 points;
- sentiment score: 15 points.

Fundamental inputs:

- PE percentile or absolute PE sanity band;
- PB percentile or absolute PB sanity band;
- ROE;
- revenue or profit growth.

Technical inputs:

- moving average trend, such as close above 20-day and 60-day moving averages;
- RSI;
- MACD histogram or DIF/DEA relationship;
- volume confirmation.

Capital-flow inputs:

- main capital net inflow or outflow;
- consecutive main capital outflow days;
- margin financing direction when available.

Sentiment/event inputs:

- limit-up streak;
- Dragon Tiger List signal when available;
- public opinion or announcement risk tags from the information repository.

The scoring rules should be simple, deterministic, and documented in tests. The
first version should not use black-box NLP or optimize weights.

## Risk Warning Engine

The risk engine returns a list of warnings and a highest action level.

Risk actions:

- `none`: no risk response;
- `watch`: record warning but do not block;
- `reduce`: reduce exposure;
- `liquidate`: force liquidation in backtest or paper simulation.

Initial rules:

- portfolio drawdown at or beyond 15% triggers `liquidate`;
- single-position drawdown beyond 8% triggers at least `reduce`;
- ST warning triggers at least `reduce`;
- goodwill ratio above 30% triggers at least `watch`;
- pledge ratio above 50% triggers at least `watch`;
- main capital net outflow for more than 3 consecutive days triggers at least
  `watch`;
- broad index below its 250-day moving average triggers at least `watch`;
- if more than 15 tracked names fall more than 3% in one day, trigger at least
  `reduce`.

When multiple rules fire, the strictest action wins. The engine should keep all
warning reasons so reports explain why an action was taken.

## Drawdown Engine

The drawdown engine consumes dated portfolio equity values and returns:

- equity curve;
- rolling peak;
- drawdown percentage per date;
- maximum drawdown;
- first date of liquidation trigger if the configured threshold is breached.

This engine should be independent of any specific strategy. DQN, baseline
strategy, and manual research runs should all use the same drawdown accounting.

## Strategy Role

DQN remains part of the project direction, but Phase 1 treats it as a downstream
consumer of the research loop. The immediate strategy work is a score-based
baseline:

- buy candidate when total score is above a configured threshold and risk action
  is not `reduce` or `liquidate`;
- sell or avoid when risk action is `reduce` or `liquidate`;
- hold otherwise.

This gives DQN a benchmark and helps verify whether RL adds value beyond a
transparent factor/risk baseline.

## Error Handling

External data failures should be explicit:

- missing Tushare token raises a clear configuration error;
- unavailable provider returns a provider-specific error rather than silent
  empty data;
- malformed records are rejected during normalization;
- information fetch deduplication should not overwrite an existing record unless
  the new record has the same stable key.

The project should not hide missing data by fabricating neutral values. Scoring
may proceed with missing components only when the output includes a clear
missing-data note and a lower confidence value.

## Testing Strategy

Tests should focus on deterministic behavior and local fixtures:

- symbol normalization for common A-share formats;
- provider registry selection and missing-token handling;
- information repository deduplication;
- score weighting sums to the required 35/25/25/15 split;
- risk rules produce the expected action level and warning reasons;
- drawdown engine computes rolling peaks, per-date drawdowns, maximum drawdown,
  and liquidation trigger date;
- baseline strategy respects risk actions before score thresholds.

Live AkShare calls can be covered by optional smoke scripts later, but core unit
tests should not require network access.

## Git Backup and Change Reports

Work should use Git as the project checkpoint system:

- commit after each coherent, verified phase;
- keep commit scope tied to the implemented module or document;
- use the configured GitHub `origin` remote as a backup target when credentials
  allow pushing;
- do not treat a remote push as production release approval;
- include a concise change report after each implementation phase with changed
  files, behavior added, verification commands, and known limitations.

## Success Criteria

Phase 1 is complete when:

1. The test suite passes locally.
2. A developer can run one deterministic fixture-backed flow from normalized
   A-share records to score, risk warnings, drawdown output, and baseline trade
   decision.
3. AkShare and Tushare provider boundaries are present, with AkShare as default
   and Tushare token handling ready for later activation.
4. Information records can be stored and queried locally by symbol or sector.
5. The DQN path is not removed, and its future state/reward design can consume
   the same score, risk, and drawdown outputs.
