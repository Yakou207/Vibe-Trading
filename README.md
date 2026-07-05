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

## Daily Pipeline

Use the daily pipeline command to run the practical research loop from one selected-universe file. It fetches/updates the information repository, archives financial-report documents, applies dictionary sentiment tags, exports classified repository files, writes an information summary, refreshes daily bars and features, builds market-state risk input, writes the RL state dataset, reports scoring coverage, and produces a baseline run report:

```bash
python scripts/run_daily_research_pipeline.py \
  --universe universe.csv \
  --start 2026-01-01 \
  --end 2026-06-30 \
  --price-source akshare \
  --information-source akshare_multi \
  --market-source akshare \
  --classified-information-output-dir data/raw/information/classified \
  --information-summary-output outputs/information_repository_summary.json \
  --buy-threshold 70 \
  --min-score-confidence 0.8 \
  --max-portfolio-drawdown 0.15 \
  --max-single-position-drawdown 0.08 \
  --max-goodwill-ratio 0.30 \
  --max-pledge-ratio 0.50 \
  --max-main-outflow-days 3 \
  --broad-market-drop-threshold 15 \
  --rl-policy-report-output outputs/research_runs/rl_buy_and_hold/run_report.json \
  --rl-policy buy_and_hold \
  --rl-policy-transaction-cost 0.001 \
  --dqn-policy-report-output outputs/research_runs/linear_q_dqn/run_report.json \
  --dqn-eval-start 2026-05-01 \
  --dqn-policy-transaction-cost 0.001 \
  --strategy-comparison-output outputs/research_runs/baseline_vs_dqn.json \
  --strategy-comparison-align-to-candidate \
  --scoring-coverage-output outputs/scoring_coverage.json \
  --stock-analysis-output outputs/stock_score_analysis.json
```

For offline testing, use `--price-source json --price-input bars.json`, `--information-source jsonl --information-input information.jsonl`, and `--market-source csv --market-input index.csv`.

After configuring `TUSHARE_TOKEN`, the same pipeline can use `--information-source tushare_fundamental` for Tushare Pro fundamental snapshots while keeping AkShare as the default daily data provider.

Run a data-source smoke check before daily jobs or after provider upgrades. It checks the current AkShare/Tushare adapter paths, writes per-source status, row counts, and returned fields. Tushare checks are skipped without `TUSHARE_TOKEN` unless `--strict` is used:

```bash
python scripts/check_data_sources.py \
  --checks akshare_daily,akshare_realtime,akshare_fundamental,tushare_daily,tushare_fundamental \
  --universe universe.csv \
  --start 2026-01-01 \
  --end 2026-01-10 \
  --output outputs/data_source_health.json
```

The daily pipeline does not run live smoke checks by default. Add `--preflight-data-sources` when you want the pipeline to run `check_data_sources.py` first across the selected universe and write `--data-source-health-output`; add `--preflight-data-source-strict` in CI or a formal daily job when skipped/failed checks should stop the pipeline.

Fetch realtime A-share quotes for intraday monitoring or ad-hoc risk checks:

```bash
python scripts/fetch_realtime_quotes.py \
  --source akshare \
  --symbols 000001,600000 \
  --output data/raw/realtime_quotes/a_share_realtime_quotes.csv
```

You can also pass `--universe universe.csv` to fetch realtime quotes for the selected research universe. Offline tests use `--source json --input quotes.json`.

Evaluate realtime risk from normalized quote CSVs. The script counts valid rows with `change_pct < -0.03` and feeds that count into the existing risk engine. You can also pass a small JSON object with `RiskInput` fields such as `portfolio_drawdown`, `single_position_drawdown`, `st_warning`, `goodwill_ratio`, `pledge_ratio`, `main_outflow_days`, and `index_below_annual_ma` so the same realtime check covers portfolio, stock-specific, market, and systemic warnings:

```bash
python scripts/evaluate_realtime_risk.py \
  --quotes data/raw/realtime_quotes/a_share_realtime_quotes.csv \
  --risk-input data/raw/realtime_risk_input.json \
  --max-position-weight 0.08 \
  --max-portfolio-drawdown 0.15 \
  --max-single-position-drawdown 0.08 \
  --max-goodwill-ratio 0.30 \
  --max-pledge-ratio 0.50 \
  --max-main-outflow-days 3 \
  --broad-market-drop-threshold 15 \
  --output outputs/realtime_risk.json
```

Summarize the information warehouse after a fetch to review category coverage, stock-data retention, risk tags, source mix, per-symbol/per-sector coverage, latest financial-report/policy/stock-data dates, and recent negative records:

```bash
python scripts/summarize_information_repository.py \
  --input data/raw/information/information.jsonl \
  --symbol 000001 \
  --sector 银行 \
  --output outputs/information_repository_summary.json
```

Export the warehouse into explicit retention-class files when you want to inspect or hand off the two data families separately:

```bash
python scripts/export_information_repository.py \
  --input data/raw/information/information.jsonl \
  --output-dir data/raw/information/classified
```

This writes `text_financial_report.jsonl`, `selected_universe_stock_data.jsonl`, and `manifest.json`. The daily pipeline runs this export after sentiment analysis, so the classified files include updated risk tags and text-sentiment metadata. It also writes `outputs/information_repository_summary.json` by default.

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

Daily bars are validated at the loader boundary before they enter features, risk, or DQN datasets. The normalizer rejects non-positive OHLC prices, `high < low`, open/close prices outside the `[low, high]` range, and negative volume or amount values.

## Phase 4 Research Run

Phase 4 connects local features, optional fundamentals, capital-flow rows, and information records into a reproducible baseline run:

```bash
python scripts/run_research_baseline.py \
  --run-id fixture-run \
  --features data/processed/akshare_research_features.csv \
  --universe universe.csv \
  --buy-threshold 70 \
  --min-score-confidence 0.8 \
  --max-portfolio-drawdown 0.15 \
  --max-single-position-drawdown 0.08 \
  --max-goodwill-ratio 0.30 \
  --max-pledge-ratio 0.50 \
  --output-root outputs/research_runs
```

The command writes `outputs/research_runs/<run_id>/run_report.json` with scores, missing fields, risk warnings, risk summary by layer/action/rule, trades, portfolio equity, drawdown, and summary metrics. Drawdown output includes point-level rolling-peak records, current underwater state (`current_drawdown`, `current_drawdown_start`, `current_underwater_days`), and episode diagnostics with start date, trough date, recovery date, depth, duration days, and recovery days. The scored baseline only buys when the score is at or above threshold and score confidence is at least 0.8, so sparse factor coverage does not create low-quality buy signals.

Use the explanation command when you need to inspect one stock's factor score. It outputs the 35/25/25/15 component weights, actual component scores, scoring reasons, and the raw or derived inputs used by each component:

```bash
python scripts/explain_stock_analysis.py \
  --features data/processed/akshare_research_features.csv \
  --universe universe.csv \
  --information data/raw/information/information.jsonl \
  --symbol 000001 \
  --trade-date 2026-01-02 \
  --output outputs/stock_analysis_explanation.json
```

Use the coverage command before trusting a batch of scores. It reports score distribution, component averages, confidence, and missing-field counts/rates across the selected universe:

```bash
python scripts/summarize_scoring_coverage.py \
  --features data/processed/akshare_research_features.csv \
  --universe universe.csv \
  --information data/raw/information/information.jsonl \
  --fundamentals data/processed/fundamentals.csv \
  --capital-flow data/processed/capital_flow.csv \
  --output outputs/scoring_coverage.json
```

Export per-stock, per-date multi-factor analysis when you need to inspect why a name was scored high or low:

```bash
python scripts/analyze_stock_scores.py \
  --features data/processed/akshare_research_features.csv \
  --universe universe.csv \
  --information data/raw/information/information.jsonl \
  --fundamentals data/processed/fundamentals.csv \
  --capital-flow data/processed/capital_flow.csv \
  --output outputs/stock_score_analysis.json
```

Each record includes total score, confidence, missing fields, and the 35/25/25/15 component scores with max score, weight, rule-based reasons, and the concrete input values used by each component.

## Risk Matrix

The risk engine exposes an auditable `RISK_RULE_CATALOG` and evaluates warnings through the same rules:

| Layer | Rule | Trigger | Action |
| --- | --- | --- | --- |
| portfolio_drawdown | portfolio_drawdown | portfolio_drawdown >= 15% | liquidate |
| single_stock_negative | position_weight | position_weight > configured max weight | reduce |
| single_stock_negative | single_position_drawdown | single_position_drawdown > 8% | reduce |
| single_stock_negative | st_warning | ST warning is active | reduce |
| single_stock_negative | negative_event_count | negative stock-specific information exists | watch |
| single_stock_negative | goodwill_ratio | goodwill_ratio > 30% | watch |
| single_stock_negative | pledge_ratio | pledge_ratio > 50% | watch |
| single_stock_negative | main_outflow_days | main_outflow_days > 3 | watch |
| broad_market_abnormal | index_below_annual_ma | broad index below 250-day moving average | watch |
| systemic_risk | broad_market_drop_gt_3pct_count | more than 15 tracked names fall over 3% | reduce |

Risk warnings in run reports and realtime risk output include `observed_value` and `threshold_value`, so each alert shows the actual trigger value beside the configured threshold.

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

Each row contains a stable `state_fields` list, numeric `state_vector`, and one-day forward return target. This is the data contract for fixed-policy evaluation and DQN-style training.

The training package also exposes a lightweight daily environment for future DQN work:

```python
from pathlib import Path

from fintech_quant.training import (
    AShareBuySellHoldEnvironment,
    group_rl_state_samples_by_symbol,
    load_rl_state_jsonl,
)

samples = load_rl_state_jsonl(Path("data/processed/rl_state_dataset.jsonl"))
episodes = group_rl_state_samples_by_symbol(samples)
env = AShareBuySellHoldEnvironment(episodes["000001.SZ"][0], transaction_cost=0.001)
observation = env.reset()  # state_vector plus current position
step = env.step("buy")     # buy, sell, or hold
```

The environment is deliberately small: one symbol per episode, one long/cash position flag, forward-return rewards, and explicit transaction cost. This keeps DQN experiments comparable with the scored baseline before adding more complex execution behavior.

Generate a simple RL-environment policy report as a sanity baseline:

```bash
python scripts/evaluate_rl_policy.py \
  --input data/processed/rl_state_dataset.jsonl \
  --policy buy_and_hold \
  --symbol ALL \
  --transaction-cost 0.001 \
  --run-id rl-buy-and-hold \
  --output outputs/research_runs/rl_buy_and_hold/run_report.json
```

The output uses the same minimal `run_report.json` fields needed by `scripts/compare_strategy_reports.py`: `run_id`, `strategy_config`, `equity_curve`, `trades`, and `summary`. Use `--symbol ALL` to evaluate every symbol in the RL dataset as an equal-weight research basket, or pass one symbol for single-stock diagnostics. Its `summary.win_rate` is based on positive reward steps, and the report records this in `summary.win_rate_basis` plus `summary.win_rate_sample_count`.

Train the first lightweight DQN-style candidate policy with no neural-network dependency:

```bash
python scripts/train_dqn_policy.py \
  --input data/processed/rl_state_dataset.jsonl \
  --symbol ALL \
  --epochs 50 \
  --learning-rate 0.05 \
  --gamma 0 \
  --eval-start 2026-05-01 \
  --transaction-cost 0.001 \
  --run-id linear-q-dqn \
  --output outputs/research_runs/linear_q_dqn/run_report.json
```

This trains `linear_q_dqn_v0`, a deterministic linear action-value policy for `buy`, `sell`, and `hold`. It is intentionally small so it can be compared against the scored baseline before adding PyTorch replay-buffer DQN. Use `--symbol ALL` for selected-universe equal-weight evaluation; omit `--symbol` to evaluate all symbols when the dataset contains more than one symbol, or pass one symbol for single-stock diagnostics. When `--eval-start` is set, rows before that date train the policy and rows on or after that date produce the out-of-sample report.

## Phase 7 Strategy Comparison

Phase 7 compares a baseline `run_report.json` against a candidate report, such as the linear Q DQN-style run:

```bash
python scripts/compare_strategy_reports.py \
  --baseline outputs/research_runs/baseline/run_report.json \
  --candidate outputs/research_runs/dqn/run_report.json \
  --output outputs/research_runs/comparison.json \
  --align-to-candidate
```

The comparison includes total return, annualized return, Sharpe, max drawdown, trade count, win rate, excess return, and walk-forward segment returns.

Use `--align-to-candidate` when the candidate is an out-of-sample DQN report with a shorter date range; it compares the candidate against the baseline equity curve over the same candidate dates. The aligned baseline trade count is also filtered to the candidate window, while baseline `win_rate_basis=closed_trades_realized_pnl` remains distinct from DQN `win_rate_basis=positive_reward_steps`. The daily pipeline can run this comparison automatically when both `--dqn-policy-report-output` and `--strategy-comparison-output` are set, and `--strategy-comparison-align-to-candidate` enables the same date alignment.

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

Before a daily run, use the source health check to see per-source record counts and errors without writing repository records:

```bash
python scripts/check_information_sources.py \
  --sources akshare_notice,akshare_policy,akshare_fundamental,akshare_financial_statement \
  --symbol 000001 \
  --start 2026-01-01 \
  --end 2026-06-30 \
  --output outputs/information_source_health.json
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

Use `tushare_fundamental` after configuring `TUSHARE_TOKEN` when you want the same selected-universe fundamental record shape from Tushare Pro `daily_basic` and `fina_indicator`:

```bash
TUSHARE_TOKEN=... python scripts/fetch_information.py \
  --source tushare_fundamental \
  --symbol 000001 \
  --start 2026-01-01 \
  --end 2026-06-30 \
  --output data/raw/information/information.jsonl
```

Use `akshare_financial_statement` when you want structured balance-sheet, income-statement, and cash-flow rows from AkShare's Sina financial-report endpoint. These are stored as selected-universe `stock_data` records so they are retained for RL training and later factor/risk extraction:

```bash
python scripts/fetch_information.py \
  --source akshare_financial_statement \
  --symbol 000001 \
  --start 2024-01-01 \
  --end 2026-06-30 \
  --output data/raw/information/information.jsonl
```

Use `akshare_pledge_ratio` when you want listed-company pledge ratio snapshots for the selected stock. These records feed the existing `pledge_ratio > 50%` risk rule:

```bash
python scripts/fetch_information.py \
  --source akshare_pledge_ratio \
  --symbol 000001 \
  --start 2026-06-01 \
  --end 2026-06-30 \
  --output data/raw/information/information.jsonl
```

Use `akshare_st_status` when you want ST warning snapshots from A-share realtime names. Names containing `ST`, such as `*ST`, are stored as `st_warning` records:

```bash
python scripts/fetch_information.py \
  --source akshare_st_status \
  --symbol 000001 \
  --start 2026-06-01 \
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
  --recent-pages 20 \
  --output data/raw/information/information.jsonl
```

`--recent-pages` controls how many AkShare notice pages are scanned from `--recent-page`. Use a larger value for three-year backfills, then rely on the repository's retention policy to keep only recent text records.

Archive the source documents behind financial-report URLs after fetching the notice index:

```bash
python scripts/archive_financial_reports.py \
  --input data/raw/information/information.jsonl \
  --output data/raw/information/information.jsonl \
  --document-root data/raw/information/financial_reports
```

The archiver downloads the original report document and writes `raw_document_path` metadata. HTML and plain-text reports also get extracted into `raw_text_path`; PDF text extraction is used when `pypdf` is available, otherwise the PDF original is still retained.

Analyze text sentiment after fetching and archiving information records:

```bash
python scripts/analyze_information_sentiment.py \
  --input data/raw/information/information.jsonl \
  --output data/raw/information/information.jsonl
```

The sentiment step uses a fixed dictionary, writes `text_sentiment_score` metadata, and adds `negative_text_sentiment` when negative wording is detected. This keeps the sentiment signal reproducible before adding heavier NLP models.

`akshare_multi` combines AkShare notices, financial-report announcements, policy/regulatory news, fundamental snapshots, structured financial statements, pledge ratio, ST status, individual fund flow, margin financing rows, and dragon-tiger board sentiment into the same classified JSONL repository.

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
