# Fintech Quant Agent

面向 A 股日频交易研究的自动化量化系统骨架。

第一版目标不是实盘下单，而是把数据获取、因子分析、RL 买/卖/持有策略、回测约束、风险管理、模拟交易和报告输出拆成清晰模块。

## Current Scope

- 市场：A 股优先，Phase 1 默认数据源为 AkShare，并保留 Tushare token-ready 适配器用于后续接入。
- 频率：日频为主，不做高频交易。
- 策略：第一版支持 RL buy/sell/hold 策略接口，同时保留多因子基线对照。
- 交易约束：多标的研究回测已建模 T+1、涨跌停、停牌、手续费、滑点；印花税和更细的部分成交仍是后续项。
- 执行：先做 paper trading，不接实盘券商。

## Phase 1 Research Loop

The first working slice is a daily A-share research loop:

```text
data providers -> information repository -> scoring -> risk warnings -> drawdown -> scored baseline strategy
```

AkShare is the default A-share provider. Tushare has a token-aware adapter for future account setup. The information repository has two retention classes: text financial/report records keep the most recent 3 years, while selected-universe stock data is retained for RL training material.

Phase 1 implementation notes and system assessment are documented in `docs/phase-one-change-report.md`.

## Phase 2 Baseline Runner

Phase 2 adds a deterministic one-symbol daily backtest runner for the scored baseline strategy. It consumes normalized bars, precomputed `StockScore` values, and optional `RiskInput` records, then outputs trades, equity curve, risk warnings, drawdown, and summary metrics.

This is the benchmark path for future DQN comparison. It intentionally keeps accounting simple before adding A-share execution constraints such as T+1, lot size, fees, slippage, and price-limit handling.

## Phase 3 Data Pipeline

Phase 3 adds a selected-universe daily data pipeline:

```bash
python scripts/refresh_research_data.py \
  --source json \
  --input bars.json \
  --universe universe.csv \
  --daily-output data/processed/akshare_research_daily.csv \
  --feature-output data/processed/akshare_research_features.csv
```

Provider mode supports `--source auto`, `--source akshare`, or `--source tushare` with `--start` and `--end`. Tests use JSON fixture mode and do not hit network providers.

Generated features include moving averages, RSI, MACD, daily returns, and rolling volatility for baseline and future DQN research.

## Phase 4 Research Run

Phase 4 connects local features, optional fundamentals, capital-flow rows, and information records into a reproducible baseline run:

```bash
python scripts/run_research_baseline.py \
  --run-id fixture-run \
  --features data/processed/akshare_research_features.csv \
  --universe universe.csv \
  --output-root outputs/research_runs
```

The command writes `outputs/research_runs/<run_id>/run_report.json` with scores, missing fields, risk warnings, trades, portfolio equity, drawdown, and summary metrics. DQN remains frozen until these baseline artifacts are stable enough for comparison.

## Phase 5 A-share Execution Constraints

Phase 5 wires practical A-share constraints into the multi-symbol portfolio runner:

- suspended stocks cannot be bought or sold
- limit-up stocks cannot be bought
- limit-down stocks cannot be sold
- T+1 blocks same-day sells after a buy
- constraints can be disabled explicitly for research comparison

## Phase 6 RL State Dataset

Phase 6 builds a deterministic JSONL state dataset for future DQN experiments:

```bash
python scripts/build_rl_dataset.py \
  --features data/processed/akshare_research_features.csv \
  --universe universe.csv \
  --fundamentals fundamentals.csv \
  --capital-flow capital_flow.csv \
  --output data/processed/rl_state_dataset.jsonl
```

Each row contains a stable `state_fields` list, numeric `state_vector`, and one-day forward return target. This is a data contract for RL training, not a trained DQN policy.

## Phase 7 Strategy Comparison

Phase 7 compares a baseline `run_report.json` against a candidate report, such as a future DQN run:

```bash
python scripts/compare_strategy_reports.py \
  --baseline outputs/research_runs/baseline/run_report.json \
  --candidate outputs/research_runs/dqn/run_report.json \
  --output outputs/research_runs/comparison.json
```

The comparison includes total return, annualized return, Sharpe, max drawdown, trade count, win rate, excess return, and walk-forward segment returns.

## Phase 8 Multi-source Information Fetch

Phase 8 expands the information repository fetcher:

```bash
python scripts/fetch_information.py \
  --source akshare_multi \
  --symbol 000001 \
  --start 2026-01-01 \
  --end 2026-06-30 \
  --output data/raw/information/information.jsonl
```

Use `akshare_policy` when you only want policy/regulatory text for a stock code or sector keyword:

```bash
python scripts/fetch_information.py \
  --source akshare_policy \
  --sector 新能源 \
  --start 2026-01-01 \
  --end 2026-06-30 \
  --output data/raw/information/information.jsonl
```

Use `akshare_fundamental` when you only want selected-universe valuation and financial-ratio snapshots:

```bash
python scripts/fetch_information.py \
  --source akshare_fundamental \
  --symbol 000001 \
  --start 2026-01-01 \
  --end 2026-06-30 \
  --output data/raw/information/information.jsonl
```

Use `akshare_financial_report` when you only want text financial-report announcements. These records are stored as `financial_report` text records and follow the three-year text retention policy:

```bash
python scripts/fetch_information.py \
  --source akshare_financial_report \
  --symbol 000001 \
  --start 2024-01-01 \
  --end 2026-06-30 \
  --output data/raw/information/information.jsonl
```

Archive the source documents behind financial-report URLs after fetching the notice index:

```bash
python scripts/archive_financial_reports.py \
  --input data/raw/information/information.jsonl \
  --output data/raw/information/information.jsonl \
  --document-root data/raw/information/financial_reports
```

The archiver downloads the original report document and writes `raw_document_path` metadata. HTML and plain-text reports also get extracted into `raw_text_path`; PDF text extraction is used when `pypdf` is available, otherwise the PDF original is still retained.

`akshare_multi` combines AkShare notices, financial-report announcements, policy/regulatory news, fundamental snapshots, individual fund flow, margin financing rows, and dragon-tiger board sentiment into the same classified JSONL repository.

## Market Risk State

Use `fetch_market_state.py` to build the market-level risk file consumed by research runs. By default it fetches the Shanghai Composite index (`sh000001`) from AkShare, computes the 250-day moving average, and writes `index_below_annual_ma`:

```bash
python scripts/fetch_market_state.py \
  --source akshare \
  --index-symbol sh000001 \
  --start 2026-01-01 \
  --end 2026-06-30 \
  --output data/raw/market_state/sh000001_market_state.csv
```

The output can be passed to `scripts/run_research_baseline.py --market-state`. If a market-state CSV contains `index_close` and `index_ma250`, the research dataset loader derives `index_below_annual_ma` automatically unless the file already provides an explicit value.

## Local Setup

```bash
source .venv/bin/activate
python -m unittest discover -s tests
```

Python 版本：当前工作区 `.venv` 使用本机 Python 3.14。

## Project Layout

```text
src/fintech_quant/
  config/        项目配置和默认研究范围
  data/          数据源接口与 AkShare/Tushare Phase 1 适配器
  features/      因子工程与特征生成
  strategies/    策略接口、多因子基线、RL buy/sell/hold 策略
  backtesting/   回测引擎、撮合、绩效指标
  risk/          仓位、止损、回撤、行业和个股约束
  training/      RL 训练入口、环境、样本切分
  execution/     模拟交易账户和未来券商接口
  reports/       回测报告、交易日志、研究记录
```

## Reference Repositories Studied

- 24mlight/A_Share_investment_Agent: A 股多智能体投研和中文市场语境。
- TauricResearch/TradingAgents: 分析师、研究员、交易员、风控团队的职责拆分。
- hsliuping/TradingAgents-CN: 中文增强、A 股数据源、界面和报告化思路。注意其混合许可证限制。
- HKUDS/Vibe-Trading: 自然语言研究工作台、回测、报告、研究记忆和策略导出。

本项目当前只借鉴架构思想，不直接复制这些仓库代码。
