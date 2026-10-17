# AI 交易桌看板逆向分析与项目优化路线（2026-10-17）

## 1. 截图对象是什么

截图来自 X 上流行的 “GROKBOT + JEV” 系列：一个跑在 Solana memecoin（pump.fun 新币）上的
“AI 交易桌”直播页面。口号 `JEV PICKS, GROK TRADES` 说明了分工：

- **Jev**：选币大脑（LLM）。被问一组固定问题，给出“软判断”分数，最后做一次 pick。
- **Grok bots**：一组按岗位分工的执行代理（SCAN / VET / SOCIAL / SIZE / FILLS / RISK / CRAWLER），
  CHIEF 自己“从不持仓”。
- **FOMO**：交易场所（下单 App），不是框架；相关教程普遍附带推广注册链接。
- **$100 → $100k 挑战**：营销型进度条。两张截图相隔约 2.5 小时，余额从 $70,041 到 $75,131，
  这与 memecoin 的高波动一致，不能证明可复现的 alpha。收益数字无法独立验证。

GitHub 上可见的同类开源实现是 `GrokDesk/grokdesk`（纸面交易、无密钥、“六个桌面 + 招聘/解雇
桌面的主管 + 自我修订的审计循环”），以及 Blink 模板 “FOMO GROK Terminal”（FastAPI +
WebSocket + Next.js + Tailwind）。

## 2. 页面逐区拆解

| 区域 | 看到的内容 | 推断的实现 |
| --- | --- | --- |
| 顶栏 | `$100 → $100K` 进度、DAY 11、UTC 时钟 | 账户权益 / 目标值；纯前端定时器 |
| 8 张代理卡 | 名称、岗位、右侧指标（0.47 / $3,621 / 1W 0L）、状态 `typing` | 每个代理是一个 LLM 角色提示词 + 工具；`typing` 是 token 流式输出的状态 |
| 像素办公室 | 等距像素风房间，角色坐在工位上，墙上大屏显示 K 线 | 预渲染背景图 + 精灵层（PixiJS / Canvas），角色状态机驱动动画；大屏嵌入行情图 |
| 粉色连线“蜘蛛” | CRAWLER 从大屏伸出折线连接卡片与 `SELL 1.58M` 标签 | 覆盖在上层的 SVG/Canvas 动画，用来把事件“指向”对应 UI 元素 |
| BALANCE 曲线 | 权益面积/折线 + 底部成交量柱 | TradingView lightweight-charts 一类的金融图表库 |
| JEV ANALYSIS | 币的 K 线 + 头像标注的买卖点 | 嵌入 DexScreener/Birdeye 图表或自绘，叠加交易标记 |
| `thresholds.py` | HARD：`min_liquidity_usd 12_000`、`max_top_10 0.60` 等；SOFT：`concentration_is_exit_risk max 0.55` 等 | 真正决定安全性的确定性阈值；SOFT 只作用于 LLM 的回答 |
| `filter.py` | `free_kill → trade_kill → chain_kill → soft_kill → pick` | 漏斗：最便宜的过滤（不花钱的算术）在前，最贵的（LLM）在后 |

### 推断的数据流

```text
pump.fun / DexScreener / Solana RPC / X API
        │  CRAWLER 拉取原始数据
        ▼
HARD 过滤（纯算术：年龄、流动性、成交、持仓集中度）  ← 便宜、确定、先跑
        ▼
LLM 软判断（Jev 回答固定问题 → SOFT 阈值）            ← 贵、不确定、后跑
        ▼
CHIEF pick → SIZE 定额 → FILLS 下单 → RISK 平仓
        │  每一步写事件
        ▼
事件总线（WebSocket）→ 前端状态仓库 → 卡片 / 像素角色 / 图表同时更新
```

**核心结论**：看板的“炫”只是事件日志的皮肤。可复用的工程思想有三条：
1. 每个代理只有一个职责，状态可见；
2. 漏斗顺序是成本顺序，确定性门禁先于 LLM；
3. 所有阈值集中展示为“桌面相信的每一个数字”，可审计。

这三条与本项目的 CSI 300 证据链是同构的，区别是本项目的每个阶段都是确定性的、可重放的，
并且有不可变 manifest 和审计。

## 3. GitHub 生态现状（2026-10 检索）

| 仓库 | 规模（检索时） | 定位 | 可借鉴点 |
| --- | --- | --- | --- |
| [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) | 35.7k stars，当天仍有提交，MIT | 个人交易代理：agent + MCP 工具 + 回测 + Web/桌面端，含 `pixel-office` 任务板 | 像素办公室只是“人工研究任务板”，明确声明分配任务不下单、职级不授予交易权限——与本项目“只读看板”原则一致 |
| [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) | 111.6k stars，Apache-2.0 | LangGraph 多代理：分析师 → 多空辩论 → 交易员 → 风控 → 组合经理 | 角色拆分与辩论结构 |
| [hsliuping/TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN) | 32.3k stars | 中文/A 股版，Tushare + AkShare | 中文报告；注意混合许可证 |
| [KylinMountain/TradingAgents-AShare](https://github.com/KylinMountain/TradingAgents-AShare) | 866 stars，PolyForm Noncommercial | 14–15 个 A 股代理 + 辩论时间线 UI + token 流式发言 | 辩论抽屉/裁决卡片的 UI；无回测和模拟交易 |
| [NoFxAiOS/nofx](https://github.com/NoFxAiOS/nofx) | 13.1k stars，AGPL-3.0 | LLM 决策 + Go 运行时硬风控（仓位、杠杆、冷却、连续失败进入安全模式） | “模型决定、代码约束”的分层，与本项目风险引擎职责划分一致 |
| [paulrobello/claude-office](https://github.com/paulrobello/claude-office) | 568 stars，MIT | 把 Claude Code 代理可视化成像素办公室：FastAPI + WebSocket + Next.js + PixiJS + Zustand | 事件 → 状态机 → 广播 → 前端 store 的分层；逐帧批量更新避免重渲染 |
| [pixel-agents-hq/pixel-agents](https://github.com/pixel-agents-hq/pixel-agents) | 9.8k stars，MIT | VS Code 扩展，每个终端一个像素角色 | 角色状态与真实活动绑定 |
| [LLMQuant/awesome-trading-agents](https://github.com/LLMQuant/awesome-trading-agents) | 索引 | 代理、MCP 服务器、回测基准汇总 | 选型入口；含 live-trade-bench 等前向评测 |

研究侧值得注意：[Look-Ahead-Bench](https://arxiv.org/abs/2601.13770) 专门测量金融 LLM 的
前视偏差。LLM 训练语料包含回测区间之后的信息，所以 **LLM 信号不能用历史回测证明有效**，
只能在前向模拟盘里验证，这一点直接约束本项目如何引入 LLM。

> 命名提示：本仓库 `Yakou207/Vibe-Trading` 与 35.7k stars 的 `HKUDS/Vibe-Trading` 同名，
> 作品集展示时容易被误认为 fork。建议对外使用独立项目名（例如 “CSI300 Evidence Desk”）。

## 4. 截图代理 ↔ 本项目阶段映射

| 截图代理 | 本项目对应 | 数据来源（cycle 产物） |
| --- | --- | --- |
| CRAWLER | 数据采集 + 健康门禁 | `decision_report.json → data_health` |
| SCAN | 多因子评分（基本面 35 / 技术 25 / 资金代理 25 / 情绪 15） | `decision_report.json → scores` |
| VET | 风险规则否决（广跌、主力流出、质押、商誉） | `risk_warnings`, `risk_summary` |
| SIZE | 8% 单票上限 × 回撤乘数 | `targets.csv` |
| FILLS | D+1 开盘模拟成交，T+1 / 涨跌停 / 停牌 / 整手 | `paper_report.json → trades, blocked_orders` |
| RISK | 8% 减仓 / 9% 清仓 / 10% 上限的组合回撤控制 | `account.drawdown_control_state` |
| AUDIT | 确定性审计门禁 | `validation_report.json` |
| CHIEF | 冻结策略、DQN/实盘开关、commit | `cycle_manifest.json → policy, git_sha` |
| thresholds.py | 审计门禁 + 冻结 policy | 同上 |
| filter.py | `data_gate → score_gate → confidence_gate → risk_veto → sizing → D+1 open` | 漏斗计数 |

## 5. 本次已实现

- `src/fintech_quant/reports/desk.py`：只读快照构建器，从最新完整 cycle 计算代理状态、
  漏斗、门禁、评分拆解、证据时间线、审计锚点起的纸面 NAV 对 CSI 300、正式回测曲线和事件日志。
- `src/fintech_quant/reports/desk_template.html`：深色/浅色双主题交易桌页面；Canvas 像素办公室
  （角色随状态动画、数据包沿流水线飞行、气泡播报事件）、代理卡打字效果、Chart.js 4.5.1 曲线
  （含表格视图）、审计门禁面板、过滤漏斗、证据时间线。
- `scripts/serve_trading_desk.py`：标准库 HTTP + SSE，监视 cycle 目录，新 cycle 落盘或行情刷新
  时推送；`--live-quotes` 盘中拉 AkShare 行情给持仓/目标估值；`--export` 导出静态单文件。
- 回放标签明确写 `POST-CLOSE REPLAY`，不把收盘后数据伪装成实时交易。

## 6. 优化路线（按优先级，遵守 AGENTS.md 的门禁）

1. **P0 证据链连续性**：当前审计 `FAILED`，原因是 2026-07-14、07-17、07-20 缺失或不完整，有效
   交易日 3/40。看板时间线已把它们标红。下一步是把 `run_csi300_post_close.py` 做成定时任务
   （17:30 首次 + 失败重试 + 通知），而不是继续加功能。
2. **P1 情绪分量是真空**：评分里情绪满分 15，但目前对所有股票恒为 5（“No negative event was
   provided”）。可以引入 LLM 公告/新闻摘要作为**前向**情绪输入：输出存为不可变产物并记录模型
   版本和提示词哈希；只在证据期之后的新窗口启用，不能改写正在计时的 policy，也不能用历史回测
   证明有效（前视偏差）。
3. **P1 多代理辩论作为影子否决层**：参考 TradingAgents 的多空辩论，只写影子账本，与 DQN 同等
   待遇——在跨窗口、跨种子稳定前不得影响模拟仓位。
4. **P2 盘中实时层**：`--live-quotes` 已能盘中估值；更进一步可接入 XTP 模拟柜台的成交回报事件
   流（另一分支），看板 FILLS 代理直接消费回报。实盘仍需全部门禁通过并经人工单独授权。
5. **P2 前端升级路径**：若需要多页面/鉴权，再迁移到 FastAPI WebSocket + Vite/React + PixiJS +
   lightweight-charts；当前零依赖方案已足够作品集演示。
6. **P3 MCP 暴露**：把快照与研究产物作为只读 MCP 资源，让 Claude 等代理基于不可变产物回答
   “今天为什么没买 X”，延续 HKUDS/Vibe-Trading 的 MCP 思路但不授予任何交易权限。
