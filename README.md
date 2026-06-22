# Fintech Quant Agent

面向 A 股日频交易研究的自动化量化系统骨架。

第一版目标不是实盘下单，而是把数据获取、因子分析、RL 买/卖/持有策略、回测约束、风险管理、模拟交易和报告输出拆成清晰模块。

## Current Scope

- 市场：A 股优先，Phase 1 默认数据源为 AkShare，并保留 Tushare token-ready 适配器用于后续接入。
- 频率：日频为主，不做高频交易。
- 策略：第一版支持 RL buy/sell/hold 策略接口，同时保留多因子基线对照。
- 交易约束：后续回测必须建模 T+1、涨跌停、停牌、手续费、印花税、滑点。
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
