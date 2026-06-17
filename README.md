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
source .venv/bin/activate
python -m unittest discover -s tests
```

Python 版本：当前工作区 `.venv` 使用本机 Python 3.14。

## AkShare Research Data Collection

Collect five years of daily data for 30 STAR Market stocks selected by current
turnover:

```bash
PYTHONPATH=src python scripts/collect_akshare_research_daily.py --limit 30 --years 5
```

Outputs:

- `data/raw/akshare/daily/`: one raw CSV per symbol.
- `data/processed/akshare_research_universe.csv`: selected stock universe.
- `data/processed/akshare_research_daily.csv`: combined daily price table.

Run a local quality audit:

```bash
PYTHONPATH=src python scripts/audit_local_daily_data.py
```

Build daily indicator features:

```bash
PYTHONPATH=src python scripts/build_daily_features.py
```

Run the current buy-and-hold walk-forward baseline:

```bash
PYTHONPATH=src python scripts/run_walk_forward_baseline.py
```

Run the real daily portfolio backtest baseline with costs, lot sizing, T+1
sellability, position limits, and drawdown risk gating:

```bash
PYTHONPATH=src python scripts/run_backtest_baseline.py
```

Run the initial Gymnasium-compatible RL environment smoke training loop with a
deterministic random policy:

```bash
PYTHONPATH=src python scripts/train_rl_random_policy.py --episodes 10
```

Run the first learnable RL v1 report with tabular Q-learning and epsilon-greedy
walk-forward train/test evaluation:

```bash
PYTHONPATH=src python scripts/run_walk_forward_q_learning.py
```

Run the strategy comparison and RL diagnostics report with Sharpe ratio,
hold-only, buy-and-hold, RSI/MACD, and Q-learning:

```bash
PYTHONPATH=src python scripts/run_strategy_comparison_report.py
```

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

## Reference Repositories Studied

- 24mlight/A_Share_investment_Agent: A 股多智能体投研和中文市场语境。
- TauricResearch/TradingAgents: 分析师、研究员、交易员、风控团队的职责拆分。
- hsliuping/TradingAgents-CN: 中文增强、A 股数据源、界面和报告化思路。注意其混合许可证限制。
- HKUDS/Vibe-Trading: 自然语言研究工作台、回测、报告、研究记忆和策略导出。

本项目当前只借鉴架构思想，不直接复制这些仓库代码。
