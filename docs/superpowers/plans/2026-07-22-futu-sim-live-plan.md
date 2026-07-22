# A 股模拟盘落地任务计划（主线：中泰 XTP 仿真）

日期：2026-07-22（同日修订）
分支：`claude/codex-v2-live-trading-cd96e7`（独立 worktree，main/V2 证据链不动）
决策记录：数据升级目标为分钟级执行+盘中风控（日频 alpha 不变）；账户策略为模拟盘优先。
QMT/Windows 桥接方案（见 `docs/superpowers/specs/2026-07-22-qmt-live-bridge-design.md`）保留为
备选，不删除。

**修订（2026-07-22 晚）**：原主线富途/老虎 OpenAPI 因两家自 2022 年合规整改后不再接受内地新用户
注册而作废。重新调研后主线改为**中泰证券 XTP 仿真环境**，Phase 0/1 相应重写；Phase 2–4 的目标
与验收标准不变，仅执行通道从富途适配器换成 XTP 适配器。

## 平台调研结论（2026-07-22 二次核实）

- **中泰 XTP 仿真（选定主线）**：个人在 XTP 官网注册后可免费申请测试账号（股票 + 算法两组，
  约一个工作日邮件下发），仿真环境部署在阿里云、互联网直连，不要求托管。官方 Python 封装
  （github.com/ztsec/xtp_api_python）提供 CentOS7+Python3.9 的 x86_64 预编译 `.so`
  （2025-08 仍在更新，API 2.2.50.8）。macOS 无原生封装，但可在 Mac 上用 linux/amd64 Docker
  容器运行——不需要任何 Windows 环境。
- 富途 OpenAPI：A 股模拟支持确认，但内地新用户无法注册，作废。
- 老虎 OpenAPI：同富途，作废。
- 掘金量化：个人免费、支持 A 股仿真，但 SDK 运行仿真策略必须连 Windows 版掘金终端
  （serv_addr 指向终端 IP:7001），等于绕回 Windows 依赖；与 QMT 一起列为"云 Windows"备选。
- 聚宽/米筐/BigQuant：网页端云模拟，无本地下单 API，策略需迁入其框架，不符合自建系统主线。
- 雪球/同花顺等模拟炒股：无 API 或仅可爬虫自动化，脆弱且违反服务条款，不采用。

## 总原则

1. 日频多因子 alpha 保持不变，V2 收盘后流水线与证据链完全不动；本分支只消费其产物
   （`targets.csv`、canonical account）。
2. 一切默认模拟环境（指令文件 `mode="simulation"` + 桥接端硬校验守卫），切实盘是人工决策且不在
   本计划范围内。
3. 每阶段有明确验收标准，未验收不进下一阶段。
4. 对账失败即停（fail closed），沿用已实现的 `reconcile_broker_state` 逻辑与 schema。

## Phase 0 — XTP 环境打通（约 1–2 天，等测试账号邮件）

| # | 任务 | 验收标准 |
|---|---|---|
| 0.1 | 【用户人工】XTP 官网（xtp.zts.com.cn）注册并在个人中心提交测试账号申请（手机号/邮箱注册，无 Google 登录；账号创建类操作助手不代办） | 收到含账号/密码/服务器地址的邮件 |
| 0.2 | Mac 上准备 linux/amd64 容器运行时（Docker Desktop / OrbStack / colima 任一）并构建 `docker/xtp` 镜像 | 容器内 `import vnxtptrader, vnxtpquote` 成功 |
| 0.3 | 连通性冒烟：容器内跑 `scripts/check_xtp_env.py`，登录仿真交易服务器，查询资产与持仓 | 打印仿真账户现金；登录/登出无错误 |
| 0.4 | 核实仿真环境细节并回写本文件：可交易范围（是否全 A）、行情服务器（Level1/分钟线可用性）、撮合规则、账户初始资金、收盘后是否可测 | 更新"调研结论"小节 |

产出：`docker/xtp/Dockerfile` + `docker/xtp/README.md`、`scripts/check_xtp_env.py`。
（富途版 0.4 的股通覆盖率检查取消：XTP 仿真为交易所级模拟，不受股通名单限制。）

## Phase 1 — XTP 适配器（复用既有订单层）

沿用 `order_instructions.json` / `broker_state.json` schema 不变，用 XTP 适配器替换 QMT
Windows 桥的位置，reconcile CLI 无需改动。

| # | 任务 | 验收标准 |
|---|---|---|
| 1.1 | 符号映射：`600000.SH` ↔ XTP `ticker='600000', market=2`（SH=2/SZ=1，含深市推断），进 `broker.py` 或独立模块 | 单测覆盖沪深往返映射 |
| 1.2 | `scripts/xtp_bridge.py`：读 order_instructions（校验 kind/schema/mode/日期，同 QMT 桥）→ 仿真服务器下限价单（insertOrder，price_type=限价）→ 回调收集成交 → 导出 broker_state.json；服务器地址硬校验为仿真环境配置 | mock XTP api 的单测全绿 |
| 1.3 | 仿真盘真实往返一笔：买入 100 股 → broker_state → reconcile | `status=OK` 的对账报告存档 |

## Phase 2 — 模拟盘每日实战循环

| # | 任务 | 验收标准 |
|---|---|---|
| 2.1 | 模拟盘账本：独立于 V2 canonical account 的 live-sim 账户日志（NAV、成交、对账结果逐日追加，含哈希链） | 单测 + 首日记录 |
| 2.2 | T+1 早盘自动化：09:20 拉实时报价 → `build_live_orders.py` → `xtp_bridge.py` 提交（launchd/cron，交易日判断复用现有日历） | 一次全自动早盘执行 |
| 2.3 | T+1 收盘后自动化：15:10 导出 broker_state → reconcile → 追加账本；失败告警并停下一日提交 | 一次全自动收盘对账 |
| 2.4 | 稳定性验收窗口 | 连续 10 个交易日无人工干预、对账全 OK |

产出：`scripts/run_sim_morning.py`、`scripts/run_sim_postclose.py`、launchd plist。

## Phase 3 — 分钟级执行 + 盘中风控（"专业化"主升级）

| # | 任务 | 验收标准 |
|---|---|---|
| 3.1 | 分钟数据通道：XTP 行情服务订阅 A 股实时行情（不足处以 AkShare 分钟线补齐），落地为带 manifest 的增量存储（沿用 V2 的 immutable 风格，独立目录，不进 V2 链） | 一个交易日的分钟数据完整落地 |
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
