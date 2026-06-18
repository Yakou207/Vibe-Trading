# Fintech Quant Agent

面向 A 股日频交易研究的自动化量化系统骨架。

第一版目标不是实盘下单，而是把数据获取、因子分析、RL 买/卖/持有策略、回测约束、风险管理、模拟交易和报告输出拆成清晰模块。

## Current Scope

- 市场：A 股优先，保留 Yahoo Finance、Finnhub、AkShare 数据接口。
- 频率：日频为主，不做高频交易。
- 策略：第一版支持 RL buy/sell/hold 策略接口，同时保留多因子基线对照。
- 交易约束：后续回测必须建模 T+1、涨跌停、停牌、手续费、印花税、滑点。
- 执行：先做 paper trading，不接实盘券商。

## Local Setup

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[data,research,dashboard,rl]"
make check-env
make test
```

Python 版本：项目声明支持 Python 3.11+。当前工作区 `.venv` 使用本机 Python 3.14。

## Local Dashboard

Run the local research dashboard with:

```bash
make dashboard
```

The dashboard reads local research outputs from:

- `outputs/strategy_comparison_report.json`
- `outputs/baseline_backtest.json`
- `outputs/data_quality_report.json`
- `outputs/factor_diagnostics_report.json`
- `data/processed/akshare_research_features.csv`

The dashboard is a research cockpit, not a live brokerage or same-close
executable trading system. It is organized around a strategy decision workflow:

- Overview: shortlist the strongest strategy by risk-adjusted performance.
- PnL: inspect baseline equity and drawdown behavior.
- Strategy Lab: inspect one strategy across walk-forward windows.
- Factors: review factor diagnostics.
- Data Ops: verify source paths, file availability, data freshness, and quality.

The dashboard data layer is configured through `DashboardConfig` and
`DashboardDataSource`, so future model upgrades can point at different outputs,
frequencies, or execution modes without rewriting the Streamlit UI.

## Project Layout

```text
src/fintech_quant/
  config/        项目配置和默认研究范围
  data/          数据源接口与 Yahoo/Finnhub/AkShare 适配器
  features/      因子工程与特征生成
  strategies/    策略接口、多因子基线、RL buy/sell/hold 策略
  backtesting/   回测引擎、撮合、绩效指标
  risk/          仓位、止损、回撤、行业和个股约束
  training/      RL 训练入口、环境、样本切分
  execution/     模拟交易账户和未来券商接口
  reports/       回测报告、交易日志、研究记录
```

## Current Engineering Contract

- `fintech_quant.data.AkShareProvider` is the primary A-share daily data adapter.
- `fintech_quant.backtesting.metrics.calculate_equity_metrics` owns return,
  Sharpe ratio, and max drawdown calculation from an equity curve.
- `fintech_quant.reports.research_results.build_dashboard_model` is the stable
  data contract for dashboards and future reports.
- `fintech_quant.reports.research_results.DashboardDataSource` is the preferred
  extensibility point for non-daily data, paper-trading feeds, and future model
  result bundles.
- `make test` is the supported local regression command.

## Reference Repositories Studied

- 24mlight/A_Share_investment_Agent: A 股多智能体投研和中文市场语境。
- TauricResearch/TradingAgents: 分析师、研究员、交易员、风控团队的职责拆分。
- hsliuping/TradingAgents-CN: 中文增强、A 股数据源、界面和报告化思路。注意其混合许可证限制。
- HKUDS/Vibe-Trading: 自然语言研究工作台、回测、报告、研究记忆和策略导出。

本项目当前只借鉴架构思想，不直接复制这些仓库代码。
