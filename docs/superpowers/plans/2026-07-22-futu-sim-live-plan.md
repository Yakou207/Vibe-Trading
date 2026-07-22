# 富途 OpenAPI 模拟盘落地任务计划

日期：2026-07-22
分支：`claude/codex-v2-live-trading-cd96e7`（独立 worktree，main/V2 证据链不动）
决策记录：执行通道选定富途/老虎 OpenAPI 主线（macOS 原生）；数据升级目标为分钟级执行+盘中风控（日频
alpha 不变）；账户策略为模拟盘优先。QMT/Windows 桥接方案（见
`docs/superpowers/specs/2026-07-22-qmt-live-bridge-design.md`）保留为备选，不删除。

## 平台调研结论（2026-07-22 核实）

- 富途 OpenAPI 明确支持 A 股模拟交易；模拟与实盘共用同一套交易接口。macOS 原生：OpenD 网关
  支持 macOS，`futu-api` 纯 Python。
- 富途实盘 A 股仅限沪深股通（A 股通）合格名单，且需要港股账户与合规确认——这只影响遥远的
  实盘阶段，不影响模拟盘。
- 老虎 OpenAPI 有模拟账户（paper account），A 股同样走股通；作为富途受阻时的备选。
- 掘金量化支持 A 股仿真，但终端偏 Windows，macOS 支持待核实；聚宽为网页端模拟，无本地 API
  主线价值。均列为备选，不投入开发。

## 总原则

1. 日频多因子 alpha 保持不变，V2 收盘后流水线与证据链完全不动；本分支只消费其产物
   （`targets.csv`、canonical account）。
2. 一切默认模拟环境（`TrdEnv.SIMULATE` 硬编码守卫），切实盘是人工决策且不在本计划范围内。
3. 每阶段有明确验收标准，未验收不进下一阶段。
4. 对账失败即停（fail closed），沿用已实现的 `reconcile_broker_state` 逻辑与 schema。

## Phase 0 — 富途环境打通（人工为主，约 1–2 天）

| # | 任务 | 验收标准 |
|---|---|---|
| 0.1 | 注册富途牛牛账号（模拟盘不要求入金；OpenAPI 需牛牛号），macOS 安装 OpenD 网关并登录 | OpenD 本机启动成功 |
| 0.2 | `pip install futu-api`，连通性冒烟：查询模拟账户资产 | 脚本打印模拟账户现金/持仓 |
| 0.3 | 核实 A 股模拟账户可交易范围（全 A 还是股通名单）与行情权限（A 股 LV1、分钟 K 线、实时报价的可用性和限额） | 写入本文件"调研结论"小节 |
| 0.4 | CSI 300 成分与 A 股通名单覆盖率检查脚本（一次性诊断） | 输出覆盖率报告；若 <95% 在报告中标红 |

产出：`scripts/check_futu_env.py`（0.2 冒烟 + 权限探测）、`scripts/check_stock_connect_coverage.py`（0.4）。

## Phase 1 — 富途适配器（复用既有订单层）

沿用 `order_instructions.json` / `broker_state.json` schema 不变，用富途适配器替换 QMT
Windows 桥的位置，reconcile CLI 无需改动。

| # | 任务 | 验收标准 |
|---|---|---|
| 1.1 | 符号映射：`600000.SH` ↔ 富途 `SH.600000`（含深市/北交所推断），进 `broker.py` 或独立模块 | 单测覆盖三市场往返映射 |
| 1.2 | `scripts/futu_bridge.py`：读 order_instructions（校验 kind/schema/mode/日期，同 QMT 桥）→ `TrdEnv.SIMULATE` 下限价单 → 轮询成交 → 导出 broker_state.json | mock 富途客户端的单测全绿 |
| 1.3 | 模拟盘真实往返一笔：买入 100 股 → broker_state → reconcile | `status=OK` 的对账报告存档 |

## Phase 2 — 模拟盘每日实战循环

| # | 任务 | 验收标准 |
|---|---|---|
| 2.1 | 模拟盘账本：独立于 V2 canonical account 的 live-sim 账户日志（NAV、成交、对账结果逐日追加，含哈希链） | 单测 + 首日记录 |
| 2.2 | T+1 早盘自动化：09:20 拉实时报价 → `build_live_orders.py` → `futu_bridge.py` 提交（launchd/cron，交易日判断复用现有日历） | 一次全自动早盘执行 |
| 2.3 | T+1 收盘后自动化：15:10 导出 broker_state → reconcile → 追加账本；失败告警并停下一日提交 | 一次全自动收盘对账 |
| 2.4 | 稳定性验收窗口 | 连续 10 个交易日无人工干预、对账全 OK |

产出：`scripts/run_futu_sim_morning.py`、`scripts/run_futu_sim_postclose.py`、launchd plist。

## Phase 3 — 分钟级执行 + 盘中风控（"专业化"主升级）

| # | 任务 | 验收标准 |
|---|---|---|
| 3.1 | 分钟数据通道：富途 API 订阅 A 股分钟 K/实时报价，落地为带 manifest 的增量存储（沿用 V2 的 immutable 风格，独立目录，不进 V2 链） | 一个交易日的分钟数据完整落地 |
| 3.2 | TWAP 执行器：单笔开盘单改为 09:30–10:00 分 N 段限价单；逐段记录实现价格 | 实现滑点报告：live-sim 实际滑点 vs paper 假设 0.0005 |
| 3.3 | 盘中风控监控进程：持仓个股实时跌幅/跌停/停牌、组合实时回撤、系统性风险信号盘中复算。仅监控+告警，不自动动作（自动减仓属于策略阈值变更，需人工批准后另立任务） | 告警日志 + 一次演练 |
| 3.4 | 执行质量对比：以 20 个交易日为窗口，统计成交率、滑点分布、TWAP vs 单笔开盘单成本差 | 对比报告，决定默认执行方式 |

## Phase 4 — 评估与下一步决策（人工复核点）

| # | 任务 | 验收标准 |
|---|---|---|
| 4.1 | live-sim 与 V2 paper 影子账户系统性偏差分析（成交率、滑点、成本、NAV 偏离） | 书面报告 |
| 4.2 | 与 V2 证据窗口（40 交易日/56 天）合并复核：策略证据 + 执行证据齐备后，人工决定是否推进实盘调研（股通合规、开户、资金——全部人工操作，不进代码） | 决策记录 |

## 明确不做（本计划范围外）

- 触碰 V2 流水线、审计器、策略阈值（70 分/0.8/8% 等）；
- 分钟级因子研究与盘中信号（列为可能的二期，待 Phase 3 验收后再议）；
- 实盘账户、真实资金、自动切换实盘的任何代码路径；
- QMT/Windows 桥的进一步开发（保留现状作为备选）。
