# Architecture Notes

## Design Assumptions

- A 股优先，因为用户更熟悉市场语境。
- 第一版做日频研究、训练、回测和模拟交易，不接实盘。
- RL 是核心研究模块，但必须和规则/多因子基线在同一回测框架下比较。
- 数据源先使用免费层工具，接口保留可替换能力。
- 训练数据可以下载到本地，但原始数据、处理后数据和模型文件不进 Git。

## Core Flow

```text
data providers -> feature pipeline -> strategy decision -> risk gate -> backtest/paper account -> report
```

## Phase 1 Module Contracts

- `data`: normalize A-share symbols and daily bars; route `source="auto"` to AkShare first so the research loop is built on a stable local schema before adding fallback providers.
- `information`: persist classified text and selected-universe stock data records with distinct retention rules.
- `features`: produce 35/25/25/15 stock scores with component reasons and missing-data confidence.
- `risk`: evaluate portfolio, stock-specific, market, and systemic risk warnings.
- `backtesting`: calculate drawdown from dated equity points independently of strategy.
- `strategies`: provide a scored baseline decision policy for future DQN comparison.

## RL Role

第一版采用单票 buy/sell/hold 决策接口：

- state: 单只股票的行情、技术指标、基本面和市场状态。
- action: buy, sell, hold。
- reward: 后续设计，至少要扣除手续费、滑点、错误持仓和回撤惩罚。
- constraints: T+1、涨跌停、停牌和仓位上限由回测/风控层执行，不让策略绕过。

## Data Storage

```text
data/raw/        原始下载数据，不进 Git
data/processed/ 处理后特征和训练样本，不进 Git
data/models/    训练后的模型和检查点，不进 Git
```

模型训练通常需要本地数据集和本地模型文件。小模型可以保存在 `data/models/`，后续如果模型变大，再引入 DVC、Git LFS 或对象存储。
