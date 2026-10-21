# Operations Guide · 运行手册

> 本文件保存全部运行命令与各阶段细节；项目概览见仓库根目录的 [README](../README.md)。

面向 A 股日频交易研究的自动化量化系统骨架。

第一版目标不是实盘下单，而是把数据获取、因子分析、RL 买/卖/持有策略、回测约束、风险管理、模拟交易和报告输出拆成清晰模块。

## Current Scope

- 市场：A 股优先，Phase 1 默认数据源为 AkShare，并保留 Tushare token-ready 适配器用于后续接入。
- 频率：日频为主，不做高频交易。
- 策略：第一版支持 RL buy/sell/hold 策略接口，同时保留多因子基线对照。
- 交易约束：多标的研究回测已建模 T+1、涨跌停、停牌、佣金最低收费、分日期印花税和滑点；更细的部分成交仍是后续项。
- 执行：先做 paper trading，不接实盘券商。

## Formal CSI 300 Point-in-Time Research

`scripts/run_csi300_research.py` 是正式 CSI 300 研究入口。它先核对 raw/processed manifest 及文件 SHA-256，再执行数据健康门禁；门禁通过后才会生成多因子基线、10% 回撤上限风控基线、逐股评分分析、RL 状态数据和相对 CSI 300 的比较报告。DQN 在后端一致性诊断通过前只保留为 `diagnostic_only`，不会提高模拟仓位。

离线链路测试：

```bash
python -m pytest tests/test_run_csi300_research_script.py -q
```

完整 CSI 300 五年研究的命令顺序如下。`anchor.csv` 和 `adjustments.csv` 必须来自可追溯的中证指数成分/调整记录；`csi300_market_state.csv` 同时提供交易日历和基准净值输入。

```bash
python scripts/build_historical_index_membership.py \
  --anchor data/raw/csi300/anchor.csv \
  --adjustments data/raw/csi300/adjustments.csv \
  --index-code 000300 \
  --start 2021-01-01 \
  --expected-members 300 \
  --output data/processed/csi300_membership.csv

python scripts/collect_point_in_time_factors.py \
  --source akshare \
  --membership data/processed/csi300_membership.csv \
  --start 2021-01-01 \
  --end 2026-07-10 \
  --run-id csi300-raw-20260710

python scripts/fetch_market_state.py \
  --source akshare \
  --index-symbol sh000300 \
  --start 2020-01-01 \
  --end 2026-07-10 \
  --output data/raw/market_state/csi300_market_state.csv

python scripts/build_point_in_time_factors.py \
  --raw-manifest data/raw/runs/csi300-raw-20260710/manifest.json \
  --trading-calendar data/raw/market_state/csi300_market_state.csv \
  --run-id csi300-processed-20260710

python scripts/refresh_research_data.py \
  --source akshare \
  --universe data/processed/csi300_membership.csv \
  --start 2021-01-01 \
  --end 2026-07-10 \
  --daily-output data/processed/csi300_daily.csv \
  --feature-output data/processed/csi300_features.csv

python scripts/validate_research_data.py \
  --features data/processed/csi300_features.csv \
  --universe data/processed/csi300_membership.csv \
  --membership data/processed/csi300_membership.csv \
  --fundamentals data/processed/runs/csi300-processed-20260710/fundamentals.csv \
  --capital-flow data/processed/runs/csi300-processed-20260710/capital_flow.csv \
  --market-state data/raw/market_state/csi300_market_state.csv \
  --expected-members 300 \
  --output outputs/csi300_data_health.json

python scripts/run_csi300_research.py \
  --processed-manifest data/processed/runs/csi300-processed-20260710/manifest.json \
  --signal-price-manifest data/processed/price-runs/csi300-signal-hfq/manifest.json \
  --benchmark data/raw/market_state/csi300_market_state.csv \
  --run-id csi300-20260710 \
  --expected-members 300
```

正式信号价格必须使用后复权（`hfq`）processed manifest。后复权保持已发生历史价格的
尺度稳定，适合 immutable 增量父链；前复权会在未来除权事件发生后改写历史尺度，因此
只允许单次诊断快照，采集器和构建器都会拒绝增量 `qfq` 父链。成交和每日估值仍使用
未复权价格，并由独立公司行为账本处理分红、送转和配股。

30 只科创板股票仅用于快速诊断。为这 30 只股票准备同格式的历史 membership/raw/processed 文件后，将最后一条命令改为 `--index-code diagnostic-star30 --expected-members 30 --run-id star30-diagnostic`；通过它确认因子有覆盖、有变化且能产生目标仓位，再运行 300 只全量链路。

数据健康或策略收益门禁失败是有效研究结果，不等同于工程故障。当前系统不承诺盈利；只有在扣除成本后持续跑赢 CSI 300、最大回撤不超过 10%、跨走窗稳定且完成至少八周连续模拟交易后，才考虑接入实盘券商。

## CSI 300 收盘后模拟交易

`scripts/run_csi300_post_close.py` 是日常 CSI 300 唯一入口。它从
`pipeline_state.json` 指向的最后一次成功 manifest 开始增量采集，核对当日 300 只成分，
刷新后复权信号价、未复权成交价、点时因子、公司行为和基准，只有数据健康通过后才执行上一交易日目标并生成
下一交易日目标。DQN 不进入这条链路。

正式计时前必须创建一次不可变启动锚点。锚点复制账户、pipeline state、正式运行清单、
正式比较和基准，验证 `hfq` 信号价、未复权成交价及文件哈希，但自身不计入八周证据：

```bash
python scripts/initialize_csi300_paper_validation.py \
  --account data/paper/csi300_baseline/account.json \
  --state data/paper/csi300_baseline/pipeline_state.json \
  --formal-run-manifest outputs/csi300_research/hfq-formal-20260713/manifest.json \
  --comparison outputs/csi300_research/hfq-formal-20260713/benchmark_comparison.json \
  --benchmark data/diagnostics/csi300_market_state_sina_20200601_20260713.csv \
  --output-root data/paper/csi300_baseline/validation
```

如果现有 epoch 已因缺失交易日永久失败，只能通过显式 supersession 建立新的非计数锚点。
命令会校验并哈希引用旧锚点、最新周期和最新审计，保留全部旧证据，然后把
`pipeline_state.json` 的 active `evidence_parent` 原子切换到新锚点：

```bash
python scripts/initialize_csi300_paper_validation.py \
  --account data/paper/csi300_baseline/account.json \
  --state data/paper/csi300_baseline/pipeline_state.json \
  --formal-run-manifest outputs/csi300_research/hfq-formal-20260713/manifest.json \
  --comparison outputs/csi300_research/hfq-formal-20260713/benchmark_comparison.json \
  --benchmark outputs/paper_trading/csi300_baseline/cycles/2026-07-21/csi300_market_state.csv \
  --output-root data/paper/csi300_baseline/validation \
  --supersede-current-epoch
```

Supersession 继承旧锚点的 formal run 和 comparison 哈希，但使用包含当前账户日期的基准
快照。它本身不计数，也不会把历史补跑日期变成连续运营证据。

如果漏跑了多个交易日且账户完全空仓（实际/影子持仓和股息税批次都为空、回撤状态为
`normal`），逐日补跑没有经济意义：空仓账户在缺口期间没有任何盈亏。此时使用 epoch bridge：
它用一次不可变增量采集整个缺口的数据并要求数据健康通过，取消过期的排队目标（记录在
`bridge_manifest.json`），把账户日期移到缺口最后一个交易日，再创建引用旧锚点、旧周期、
旧审计和 bridge 记录的 schema-2 非计数锚点。任一步失败都不会改变正式账户和 state：

```bash
python scripts/bridge_csi300_paper_epoch.py \
  --as-of 2026-10-16 \
  --state data/paper/csi300_baseline/pipeline_state.json \
  --account data/paper/csi300_baseline/account.json \
  --membership data/diagnostics/csi300_official_adjustments/csi300_membership_20210615_20260630.csv \
  --comparison outputs/csi300_research/hfq-formal-20260713/benchmark_comparison.json \
  --formal-run-manifest outputs/csi300_research/hfq-formal-20260713/manifest.json \
  --reason "2026-07-22 至 2026-10-16 漏跑，账户全程空仓"
```

`--as-of` 必须是基准数据里最新的已收盘交易日。bridge 之后下一交易日照常运行
`run_csi300_post_close.py`，审计返回 `COLLECTING` 才算新 epoch 第 1 个计数日。

锚点成功附加到状态文件后，每个交易日只运行一条命令：

```bash
python scripts/run_csi300_post_close.py \
  --as-of 2026-07-14 \
  --state data/paper/csi300_baseline/pipeline_state.json \
  --account data/paper/csi300_baseline/account.json \
  --membership data/diagnostics/csi300_official_adjustments/csi300_membership_20210615_20260630.csv \
  --comparison outputs/csi300_research/hfq-formal-20260713/benchmark_comparison.json
```

成功证据写入 `outputs/paper_trading/csi300_baseline/cycles/<日期>/`，包含当日决策、
数据健康、目标、paper 日报、dashboard、V2 cycle manifest 和 `validation_report.json`。
每个 V2 manifest 精确引用启动锚点或前一日 manifest，固定使用 0.03% 佣金、5 元最低佣金、
分日期卖出印花税、个人股息税、0.05% 滑点和 `do_not_subscribe` 配股策略。失败时查看该日期目录
以及对应 immutable raw run 的 `manifest.json`/scope error；正式 paper 账户和 pipeline state
不会因为失败的数据或报告向前推进。重复提交已完成日期只做证据一致性检查，不会重复成交。
因子 processed run 只有在 raw parent、交易日历和价格特征三个 SHA-256 均一致时才会复用；
任一变化都会创建新的 immutable `-retry-N` run。paper 执行前还会要求本次日期正好是 active
evidence parent 之后的下一个 CSI 300 交易日，存在缺口时账户和 pipeline state 不会变化。

可随时独立重跑审计：

```bash
python scripts/audit_csi300_paper_validation.py \
  --anchor data/paper/csi300_baseline/validation/anchor-20260713/anchor_manifest.json \
  --cycle-root outputs/paper_trading/csi300_baseline/cycles \
  --output outputs/paper_trading/csi300_baseline/validation_report.json
```

审计状态只有四种：`NO_EVIDENCE` 表示尚无新 V2 交易日；`COLLECTING` 表示证据完整但
未满 40 个交易日/56 个自然日或绩效门槛尚未满足；`FAILED` 表示证据、执行、数据、风险
或完整窗口绩效门槛失败；`ELIGIBLE_FOR_REVIEW` 仅表示可以人工复核，绝不等于实盘授权。
审计在模拟成交提交后运行，因此审计故障会显式报错，但不会擦除已经提交的账户和交易记录。
每次成功审计的周期内报告是不可变权威记录；根级 `validation_report.json` 是其
byte-identical 原子镜像，pipeline state 的 `validation_report` 引用指向周期内报告。
状态指针会先于根镜像发布；如果根镜像写入失败，同日重放会从不可变周期报告确定性恢复，
不会重复成交。

这个入口只更新本地模拟账户，从不连接券商或发送真实订单。连续八周证据、扣费后相对
CSI 300 正超额收益和不高于 10% 的回撤门禁全部通过前，禁止接入实盘。即使状态达到
`ELIGIBLE_FOR_REVIEW`，系统仍保持 `live_trading_authorized=false`，DQN 也不得增加模拟仓位。

### 定时自动运行（launchd）

`scripts/run_scheduled_csi300_post_close.py` 是上面固定入口的调度包装，由
`deploy/launchd/com.vibetrading.csi300-post-close.plist` 每小时第 30 分钟触发；是否该跑由包装器按
Asia/Shanghai 时间决定，Mac 切换时区（例如出差到伦敦）不影响。包装器只调用 `run_csi300_post_close.py`（固定参数）和
`audit_csi300_paper_validation.py`，不改阈值、不启用 DQN、不连接券商，也不直接写账户、
state 或 manifest。每次运行：

1. 要求主仓库在 `main` 分支且没有未提交的 tracked 改动，否则阻止运行并通知；
2. 用 AkShare 新浪交易日历确定目标交易日：已过 17:30 的当日，或之前最近的交易日
   （因此睡眠后补触发也安全）。state 已是该日期则静默退出；
3. 若 state 不是目标日的前一交易日（证据缺口），阻止运行并通知，不会跨缺口自动推进；
4. 运行固定入口；失败且账户/state 哈希未变时，每 30 分钟重试，最多 5 次；若失败时账户或
   state 已变化，则不重试并通知；
5. 成功后运行独立审计并写入根目录 `validation_report.json`；审计出错或状态为 `FAILED` 时通知。

日志：`outputs/automation/csi300_post_close/<时间戳>.log`（含子进程输出）和
`runs.jsonl`（每次运行一行摘要）；launchd 自身输出在 `~/Library/Logs/VibeTrading/launchd.*.log`。无事可做的整点触发只在 `runs.jsonl`
记一行 `up_to_date`，不留单独日志。

launchd 本身不能打开 `~/Desktop` 下的任何路径：重启后登录时加载的任务会被 macOS 隐私保护拦下，退出码
78（EX_CONFIG）。因此 plist 不设 WorkingDirectory，launchd 日志放在 `~/Library/Logs`。第一次自动运行时
macOS 可能弹窗询问 python3.14 访问“桌面”文件夹，需点允许。失败通知使用
macOS 本地通知（`osascript`）。launchd 不继承登录 shell 的环境变量，plist 中显式设置了与手动运行相同的
`HTTP_PROXY`/`HTTPS_PROXY`（`127.0.0.1:1082`）；代理端口变化时需同步修改 plist 并重新安装。

安装（由用户手动执行；plist 中路径固定为 `/Users/yakou/Desktop/Vibe-Trading`）：

```bash
mkdir -p outputs/automation/csi300_post_close ~/Library/Logs/VibeTrading && cp deploy/launchd/com.vibetrading.csi300-post-close.plist ~/Library/LaunchAgents/ && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.vibetrading.csi300-post-close.plist
```

立即手动触发一次（检查日志与通知）：

```bash
launchctl kickstart gui/$(id -u)/com.vibetrading.csi300-post-close
```

卸载：

```bash
launchctl bootout gui/$(id -u)/com.vibetrading.csi300-post-close && rm ~/Library/LaunchAgents/com.vibetrading.csi300-post-close.plist
```

Mac 睡眠时错过的整点触发会在唤醒后补一次；关机则不会，开机后的下一个整点会补跑当天。启用前请暂停其他会运行同一入口的
自动化（如 `/Users/yakou/.codex/automations/csi300/automation.toml`）。

## 交易桌实时看板

`scripts/serve_trading_desk.py` 把最新完整 V2 cycle 渲染成“交易桌”视图：8 个桌面代理
（CRAWLER 数据门禁、SCAN 评分、VET 风险否决、SIZE 仓位、FILLS 执行、RISK 回撤、AUDIT 审计、
CHIEF 主管）对应已有的确定性流水线阶段，并配有像素办公室动画、过滤漏斗、审计门禁、评分拆解、
纸面 NAV 对 CSI 300 曲线和正式回测曲线。只读：不修改账户、不下单。零第三方依赖（标准库
HTTP + SSE），新 cycle 落盘后自动推送到浏览器。

```bash
python scripts/serve_trading_desk.py            # http://127.0.0.1:8765
python scripts/serve_trading_desk.py --live-quotes --quote-interval 30   # 盘中 AkShare 行情估值
python scripts/serve_trading_desk.py --export outputs/trading_desk.html  # 静态单文件快照
```

逆向分析与路线图见 [`docs/research/2026-10-17-ai-trading-desk-teardown.md`](research/2026-10-17-ai-trading-desk-teardown.md)。

### 选股页与 Top 5 影子交易池

交易桌的“选股”页（`http://127.0.0.1:8765/picks`）可以按代码或名称搜索当前 CSI 300 成分股，
对单只股票给出 Martin Luk 式四步检查（强势股 → 8 周整理平台 → 平台内强度 → 支撑共振急跌收复）、
K 线与 9/21/50 EMA、锚定在半年高低点的 AVWAP、共振区和参考止损、多因子基线分项，以及
“入场候选 / 观察 / 暂不入场 / 回避”的结论。数据只读取 pipeline state 已哈希绑定的价格快照和
决策报告；图表价位按最新未复权/后复权比例换算到当前价格尺度。

筛选排名前五进入影子交易池。池子每个交易日在收盘周期之后的固定时段（建议 18:30）刷新一次：
上一日触发的成员按今日开盘买入（停牌、开盘涨停、开盘低于止损则跳过），止损为信号日低点，
收盘跌破 9 EMA 离场，T+1 当日不卖。池子是独立的影子账户，按 hfq 价格计收益，**不计入 V2
证据、不改变计数账户**，只写 `outputs/momentum_pool/`：

```bash
python scripts/refresh_momentum_pool.py                              # 每日固定时段刷新
python scripts/refresh_momentum_pool.py --replay-start 2024-01-02    # 按时点成分历史回放
python scripts/refresh_momentum_pool_v2.py                           # v2：观察名单 + 风险仓位 + 回撤刹车，写 outputs/momentum_pool_v2/
python scripts/refresh_momentum_pool_v2.py --replay-start 2024-01-02 # v1 与 v2 同一筛选回放对比
```

方法改写、回放结果和局限见 [`docs/research/2026-10-17-martin-luk-momentum-setup.md`](research/2026-10-17-martin-luk-momentum-setup.md)。
v2 的预先声明规则与单次回放见 [`docs/research/2026-10-19-shadow-pool-v2.md`](research/2026-10-19-shadow-pool-v2.md)。

### 全平台信息、NLP、财报分析与 Jev 判断

选股页搜索一只股票后，下方会汇总这只股票的全平台信息（AkShare）：东方财富个股新闻、公司公告
（近 120 天）、券商研报（评级与 EPS 预测）、深市互动易问答、千股千评评分和同花顺财务摘要。每个
来源单独超时、单独显示状态，按股票按日缓存在 `outputs/research_cache/`。

- **事件 NLP**（`information/event_nlp.py`）：规则化识别减持、回购、问询、立案、业绩预增/下滑、
  中标、解禁、稀释等事件，处理“不存在/未发生”等否定；公告权重 1.0、新闻 0.7、互动易提问 0.3，
  14 天半衰期汇总成 −1~+1 的事件情绪。
- **财报趋势**：最近 8 期营收/净利/扣非同比、年化 ROE、净利率同比变化、经营现金流，给出逐条结论；
  研报给出近 90 天评级分布与 EPS 预测中位数。
- **Jev**（`research/jev.py`）：LLM 只读取上面整理好的资料包，回答 5 道固定问题（负面事件风险、
  财报支撑、催化剂质量、拥挤度、形态与基本面一致性），以 JSON 给 0–1 分；再由固定的 SOFT 阈值得出
  支持 / 中性 / 否决。temperature 0，记录模型、提示词哈希、资料包哈希和原始回复到 `outputs/jev/`，
  同一资料包只调用一次。Jev 只是参考：不能把技术面的“回避”变成入场，不影响计数策略、影子池或证据。

启用 Jev：在仓库根目录的 `.env`（已被 git 忽略）中填写，看板启动时自动读取：

- **TypeSafe Jev 决策模型（推荐）**：`JEV_MODEL=Jev 1.14` + `OPENROUTER_API_KEY`。经 OpenRouter
  decisions 接口发送“资料包 + 类型化问题”，5 道题以有序等级的 `score` 题提问，另加一题 `choice`
  整体倾向；Jev 直接返回各等级概率，用概率加权后的等级（0–1）套同一组 SOFT 阈值。一次约 0.0002 美元、
  2–5 秒；记录保存实际服务的快照与费用。
- **DeepSeek（对话模型）**：只填 `DEEPSEEK_API_KEY`（默认 `deepseek-flash`），会写出文字理由与总结。
- 也支持 `ANTHROPIC_API_KEY`，或 `OPENAI_API_KEY` + `JEV_MODEL` + `JEV_BASE_URL`。

判断记录按“股票 + 资料包哈希 + 问题集哈希 + 模型”存档，换模型或改问题都会重新判断。未配置时
其余信息照常显示。这些信息与 NLP 只用于展示和 Jev，计数基线的情绪分量没有改动。

## 盘前选股简报与人工执行台账

系统只做研究，真实下单由人完成。简报只读取最近一个完整的 V2 收盘周期
（`cycle_manifest.json`、`targets.csv`、`paper_report.json`、`decision_report.json`），
先核对 manifest 哈希，不新增策略、不改任何阈值（买入阈值、置信度、8% 单票上限均取自
manifest 的 `policy`）。简报、竞价检查和人工台账都不计入 V2 模拟证据，也不会写入
`cycles/`、`data/paper/` 下的账户或 state 文件；输出路径落在这些目录内会直接报错。

每个交易日的流程：

**08:45 生成盘前简报。** 对每个目标股和 65–70 分的“差一点”名单列出分项得分与理由、
风险标记、按给定资金计算的整手数量（含 5 元最低佣金；科创板不足 200 股记为 0）、
以昨收计算的涨停/跌停价（主板 10%，创业板/科创板 20%，北交所 30%；主板 ST 自
2025-07-07 起为 10%），以及待人工核对的隔夜公告占位。差一点名单只供观察，不是目标。

```bash
python scripts/build_premarket_brief.py --capital 100000
```

输出 `outputs/premarket/<信号日>/brief.json` 和 `brief.html`。文件只写一次；同内容重跑
是空操作，内容不同则报错，不会覆盖。

目标股和差一点名单旁边另列“v2 research”研究评分（横截面分位与类别分解），只作对照，
不改变目标、权重或股数，也不计入证据。它读取 `outputs/research/scoring_v2/latest_scores.json`，
快照日期必须等于信号日，否则简报只注明快照过期。生成简报前先刷新（约 30 秒）：

```bash
python scripts/run_scoring_v2.py --offline
```

**09:25 集合竞价检查（可选）。** 用简报打印的 `quote_symbols=` 列表抓竞价价格，再对照简报：

```bash
python scripts/fetch_realtime_quotes.py --symbols 600415,601058 --output outputs/premarket/quotes_0925.csv
```

```bash
python scripts/build_premarket_brief.py --auction --quotes outputs/premarket/quotes_0925.csv
```

生成 `auction.json` 和 `brief_auction.html`，标记 `at_limit_up_cannot_buy`（竞价已到涨停，
基本无法买入）、`near_limit_up`（距涨停 1% 内）、`large_gap_up`/`large_gap_down`（相对昨收
跳空 ≥5%）和 `no_auction_quote`，并按竞价价重算整手数量。

**人工下单。** 是否下单、下多少由人决定；系统不连接任何券商。

**15:30 登记人工执行台账。** 每笔成交或放弃各记一行，写入
`data/human_execution/ledger.csv`（已加入 `.gitignore`，只追加不改写）：

```bash
python scripts/human_execution_ledger.py add --trade-date 2026-07-22 --signal-date 2026-07-21 --symbol 002142 --action buy --shares 200 --fill-price 31.52 --fees 5
```

```bash
python scripts/human_execution_ledger.py add --trade-date 2026-07-22 --signal-date 2026-07-21 --symbol 600415 --action skip --skip-reason "竞价涨停"
```

校验规则：成交日必须晚于信号日；买入须为 100 股整数倍（科创板 ≥200 股）；成交价必须在
简报的跌停/涨停区间内；`skip` 必须写原因且只能针对目标股或模拟账户的卖出名单。

当日收盘周期跑完后生成对比报告：

```bash
python scripts/human_execution_ledger.py report --signal-date 2026-07-21
```

报告以昨收为决策价，计算人工与模拟账户的执行落差（implementation shortfall，元和 bp，
含费用）、人工相对模拟成交价的 bp 差、放弃率、未登记率和简报外交易。模拟成交取自
`executed_signal_date` 等于该信号日的周期 `paper_report.json`，读取前核对其 manifest 哈希。

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
  --dqn-drawdown-penalty 0.5 \
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

For information-side monitoring, add `--preflight-information-sources` to the daily pipeline. It runs `check_information_sources.py` across the selected universe's stock symbols and sectors before repository fetches, then writes `--information-source-health-output` with per-source record counts, categories, and errors.

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

Generated features include moving averages, 20-day selected-universe relative-strength rank (`rs_rank_20d`), RSI, MACD, daily returns, and rolling volatility for baseline and future DQN research.

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

Each record includes total score, confidence, missing fields, and the 35/25/25/15 component scores with max score, weight, rule-based reasons, and the concrete input values used by each component. The technical component uses MA20, MA60, selected-universe RS rank, RSI, MACD, and volume confirmation while keeping the technical weight capped at 25%.

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

The environment is deliberately small: one symbol per episode, one long/cash position flag, forward-return rewards, explicit transaction cost, and an optional drawdown penalty. This keeps DQN experiments comparable with the scored baseline before adding more complex execution behavior.

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
  --drawdown-penalty 0.5 \
  --run-id linear-q-dqn \
  --output outputs/research_runs/linear_q_dqn/run_report.json
```

This trains `linear_q_dqn_v0`, a deterministic linear action-value policy for `buy`, `sell`, and `hold`. It is intentionally small so it can be compared against the scored baseline before adding PyTorch replay-buffer DQN. Use `--symbol ALL` for selected-universe equal-weight evaluation; omit `--symbol` to evaluate all symbols when the dataset contains more than one symbol, or pass one symbol for single-stock diagnostics. When `--eval-start` is set, rows before that date train the policy and rows on or after that date produce the out-of-sample report. `--drawdown-penalty` subtracts an extra penalty from held losing steps during training, leaving evaluation returns unchanged.

For the PyTorch DQN backend, install the optional RL dependencies and run rolling walk-forward validation on the same RL state JSONL:

```bash
python scripts/run_dqn_walk_forward.py \
  --input data/processed/rl_state_dataset.jsonl \
  --symbol ALL \
  --train-years 2 \
  --eval-years 1 \
  --episodes 5 \
  --batch-size 64 \
  --transaction-cost 0.001 \
  --drawdown-penalty 0.5 \
  --output outputs/research_runs/torch_dqn_walk_forward/report.json
```

This trains `torch_dqn_v1` separately inside each train window and evaluates only on the later held-out window. The Q-learning branch history is merged, but the main research path exposes only DQN training commands.

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
  --universe universe.csv \
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
