# Vibe-Trading CSI 300 handoff

Last reviewed: 2026-10-19 Asia/Shanghai
Repository: `/Users/yakou/Desktop/Vibe-Trading`
Remote: `https://github.com/Yakou207/Vibe-Trading.git`
Implementation branch: `main` (V2 repair merged; fresh epoch bridged on 2026-10-17)

## Resume here

1. Read `AGENTS.md` and this file completely.
2. Run `git status --short`, `git branch --show-current`, `git rev-parse HEAD`, and
   `git rev-parse origin/main`. Resume only from a clean `main` that matches `origin/main`.
3. Do not connect a broker, send an order, enable DQN exposure, tune thresholds, or claim that
   historical returns prove future profit.
4. Inspect the canonical paper account, pipeline state, validation anchor, and validation report
   before running a new date.
5. For a fresh trading session use only `scripts/run_csi300_post_close.py`; do not reconstruct the
   daily chain manually.

## Current outcome

The CSI 300 research platform and paper-trading evidence V2 are implemented. The platform has a
working five-year historical baseline, point-in-time data controls, A-share paper execution,
portfolio drawdown control, immutable data manifests, an anchored V2 evidence chain, and a
deterministic readiness auditor.

This is not deployable-profit proof. At the time of this handoff:

- the formal universe is CSI 300, not the earlier 30-stock STAR Market fixture;
- the point-in-time membership history has 300 active names on each checked date, 439 unique stocks,
  and 461 membership intervals;
- on 2026-10-17 the all-cash account was bridged from `2026-07-21` to `2026-10-16` with
  `scripts/bridge_csi300_paper_epoch.py`: one immutable data increment for the gap, fresh data health,
  seven stale 2026-07-21 targets cancelled, and the non-counted schema-2 anchor
  `anchor-20261016-epoch-2` superseding the original anchor, the 2026-07-21 cycle and audit, and the
  bridge record;
- the canonical account and pipeline state are dated `2026-10-16`; cash is `100000.0`, actual and
  shadow positions are empty, nothing is queued, and the drawdown regime is `normal`;
- the 2026-10-19 cycle is the first counted session of epoch 2 (audit `COLLECTING`, `valid_sessions=1`,
  cycle-local report sha256 `60ffe505fd2595f8350dcf992a58ac248b7b5b45f32fab130411d0196b9b5862`); the 2026-10-20 cycle is the second (`valid_sessions=2`, cycle manifest sha256
  `23810d39c170d35ef9d66337c466cb110563085fa7083c55dc89d225340ce48c`; one transient Sina failure on
  `603993.SH` failed closed and a plain resume completed it); the 2026-10-21 cycle is the third (`valid_sessions=3`, cycle manifest sha256
  `83bc21c72e64f6fbf3457a9ccac57d68457c82367dc38733a267d72a8012c9b5`, run by the launchd job); it
  queued no targets because the broad-market rule emitted `reduce` for all 299 members, so the
  2026-10-22 open liquidates the book; the next run is 2026-10-22; `601059.SH` is a confirmed suspended
  member (no price after 2026-09-14 in both sources) and is listed but not scored;
- complete schema-version-2 cycles exist for `2026-07-15`, `2026-07-16`, and `2026-07-21`; all
  remain preserved failed evidence under the original anchor;
- the latest cycle-local audit loads `valid_sessions=3` but remains `FAILED` because the original
  anchor-to-cycle chain has missing CSI 300 sessions;
- operationally, the accepted continuous evidence count remains zero;
- `live_trading_authorized=false` and DQN paper exposure is disabled;
- the Codex weekday 17:30 automation is `PAUSED`; the launchd wrapper
  `scripts/run_scheduled_csi300_post_close.py` is merged on `main` (see "Scheduled automation
  (launchd)" below and `docs/operations.md`) and was installed on 2026-10-20; a kickstart test
  returned `up_to_date` for state 2026-10-20 (Desktop files readable, calendar fetched via proxy);
- the 2026-07-15 cycle passed data-health, approved-policy, execution-integrity, drawdown, DQN-off,
  and live-off gates, but failed the anchor-to-cycle trading-session continuity gate;
- the 2026-07-14 factor/benchmark mismatch was caused by incomplete processed-stage reuse
  validation, not by provider data or the equality gate; the code repair now binds every material
  factor dependency;
- explicit schema-version-2 epoch supersession, pre-commit session continuity, and canonical latest
  audit publication are implemented, but no provider-backed supersession or fresh counted cycle was
  run during the repair.

## Canonical state and hashes

The latest mutable canonical values were recorded after the 2026-10-17 bridge:

| Artifact | State | SHA-256 |
|---|---|---|
| `data/paper/csi300_baseline/account.json` | `last_processed_date=2026-10-16`, cash 100000, no positions, nothing queued | `795bda6210984fffe048ad51724534495c43bdb4e5bfe0722a5928c12d571740` |
| `data/paper/csi300_baseline/pipeline_state.json` | `last_successful_as_of=2026-10-16`, active parent is the epoch-2 anchor | `868adb303d28cdd02e1d40df23675bc3df7c4a3e458068988dba18ac9c29c7be` |
| `data/paper/csi300_baseline/validation/anchor-20261016-epoch-2/anchor_manifest.json` | active non-counted schema-2 anchor | `eb3bbf2d599d8412fec7a68b522b019f6ba9f5905f9eea1606c85b733027b65d` |
| `data/paper/csi300_baseline/validation/bridge-20260721-20261016/bridge_manifest.json` | bridge record: cancelled targets, pre-bridge account/state snapshots, bridged manifests | `f0e183509c3d293e2d9e1a89c95e8d285519b630955f93094ada743836a7d7cd` |
| `data/paper/csi300_baseline/account.json` before the bridge | `last_processed_date=2026-07-21` (snapshot kept as `bridge-20260721-20261016/account_before.json`) | `6d2ddd37f7d1415cae49a7b728e05a5b8f5dfa028547f418f522845b10fe89b1` |
| `data/paper/csi300_baseline/validation/anchor-20260713/anchor_manifest.json` | non-counted anchor | `13c2ead2826740a7426e9ffb557b23219c8abfa3ab3de73d174be9ab9c0c3a2a` |
| `outputs/paper_trading/csi300_baseline/cycles/2026-07-15/cycle_manifest.json` | complete V2 cycle chained to the original anchor | `66ec15a3d78c9181b88cb7be19e23f5e2c88c6ac91ee5d79c8899a84c88f1cbb` |
| `outputs/paper_trading/csi300_baseline/cycles/2026-07-15/validation_report.json` | `FAILED`, one loaded session, missing `2026-07-14` | `1b2846aae18223ad8809ee80fc9d4d6ba8c359ffbbd55c07f2f75f41779fb01e` |
| `outputs/paper_trading/csi300_baseline/cycles/2026-07-21/cycle_manifest.json` | latest complete preserved V2 cycle under the original anchor | `1c016de2599196e8034ec410b8c52717df88499d7aa15d6f790bd86dd5085cfc` |
| `outputs/paper_trading/csi300_baseline/cycles/2026-07-21/validation_report.json` | `FAILED`, three loaded sessions with continuity gaps | `e73b81efda51f6e0b6323c1b4973e91789bdb0f681a360c2c65d9002d344ba66` |
| `outputs/paper_trading/csi300_baseline/validation_report.json` | stale root summary: `NO_EVIDENCE`, zero sessions | `23209bf404d408f076226050804dcc786d75f266f62f747d5cd0328f06ebccc2` |
| `outputs/paper_trading/csi300_baseline/cycles/2026-07-15/dashboard.html` | committed V2 cycle dashboard | `b2fd082dabce66c18af01eaa0148ccaf78be8e84f07e59a0737cbcd3edee4254` |
| `outputs/csi300_research/hfq-formal-20260713/pnl_curve.json` | 1,231 formal CSI 300 comparison points | `abb86cff7adc98fcfb09a0a21da4fe610a9b7a671f1a927e7bdf0290f7f64107` |
| `outputs/paper_trading/csi300_baseline/hfq_formal_dashboard.html` | formal backtest dashboard with PnL curve | `147addb8a7fe9f225cce0ce642a9986c378ede58f4aeae2804b99534e81daecc` |

The 2026-07-21 cycle-local validation report is the final audit of the superseded epoch. The
root-level artifact is still the preserved stale `NO_EVIDENCE` file until the first new-epoch cycle
publishes its audit. The repaired entrypoint atomically mirrors the next successful
audit and stores its cycle-local reference in pipeline state. Account and pipeline-state hashes
must not change on a pre-commit failure.

## Approved paper policy

The counted V2 path must remain exactly:

- stock selection: scored 35/25/25/15 multi-factor baseline;
- entry score `70.0`, minimum confidence `0.8`, maximum stock weight `0.08`;
- portfolio exposure reduction at 8% drawdown, liquidation trigger at 9%, validation limit 10%;
- signal prices `adjust=hfq`;
- execution and mark-to-market prices `adjust=none`;
- commission `0.0003`, minimum commission CNY 5, date-specific sell stamp duty;
- slippage `0.0005`;
- individual FIFO dividend tax at 20%/10%/0%;
- rights issues `do_not_subscribe`;
- `dqn_exposure_enabled=false` and `live_trading_enabled=false`.

The authoritative policy object is `approved_paper_policy()` in
`src/fintech_quant/execution/paper_evidence.py`.

## Daily chain

```text
official/current 300-member check
  -> hfq signal-price immutable increment
  -> unadjusted execution-price immutable increment
  -> CSI 300 benchmark refresh
  -> point-in-time fundamentals and price-volume proxy
  -> distributions and rights-issue ledger
  -> fresh data-health and decision report
  -> execute prior close targets at current open
  -> mark current close NAV and queue current targets
  -> atomically stage account/report/targets/dashboard/V2 manifest
  -> write pipeline state
  -> audit the anchor-to-cycle evidence chain
```

The fixed daily command is:

```bash
/Users/yakou/Desktop/Vibe-Trading/.venv/bin/python scripts/run_csi300_post_close.py \
  --as-of YYYY-MM-DD \
  --state data/paper/csi300_baseline/pipeline_state.json \
  --account data/paper/csi300_baseline/account.json \
  --membership data/diagnostics/csi300_official_adjustments/csi300_membership_20210615_20260630.csv \
  --comparison outputs/csi300_research/hfq-formal-20260713/benchmark_comparison.json
```

Run it only after the requested A-share session has ended and provider data is available. A
same-date canonical replay only re-audits completed evidence. A failed raw stage creates a new
immutable `-retry-N` run; never delete or edit prior manifests to force progress.

Independent audit command:

```bash
/Users/yakou/Desktop/Vibe-Trading/.venv/bin/python scripts/audit_csi300_paper_validation.py \
  --anchor data/paper/csi300_baseline/validation/anchor-20260713/anchor_manifest.json \
  --cycle-root outputs/paper_trading/csi300_baseline/cycles \
  --output outputs/paper_trading/csi300_baseline/validation_report.json
```

## 2026-10-22 execution bug fix (not a strategy change)

The 2026-10-21 cycle sold only 2,100 of 2,200 `601018.SH` shares although the name had left the
targets. Root cause in `src/fintech_quant/execution/paper_account.py`: the sell size was
`int(abs(value_diff) // execution_price)` and `7876.0 // 3.58 == 2199.0` in floating point, which
lot rounding turned into 2,100. The 100-share remainder could never be sold, because value
differences below one lot are skipped. The formal backtest sells `position.shares` outright, so paper
and backtest disagreed; the auditor checks queued targets and weight limits but not that dropped
names are fully exited, so it did not flag the cycle.

Fix (merged before the 2026-10-22 run): a name whose target weight is zero is sold in full, an odd
lot only together with the whole position (as A-share rules allow), and partial sells use a 1e-9
tolerance instead of a raw floor. Targets, scores, thresholds, risk rules and costs are unchanged,
so this is an execution-correctness repair, not strategy tuning, and the epoch-2 window continues.
The 2026-10-21 cycle stays as recorded. Regression tests: `PaperFullExitTest` in
`tests/test_paper_trading_loop.py`.

## Scheduled automation (launchd)

Added 2026-10-17. Missed post-close runs were the operational cause of the failed audit: as of
2026-10-17 the canonical state is dated `2026-07-21`, and the 2026-07-21 cycle-local audit is
`FAILED` with missing sessions `2026-07-14`, `2026-07-17` and `2026-07-20`. The Codex automation
at `/Users/yakou/.codex/automations/csi300/automation.toml` is `PAUSED`.

`scripts/run_scheduled_csi300_post_close.py` is a deterministic wrapper started by
`deploy/launchd/com.vibetrading.csi300-post-close.plist` on weekdays at 17:30 and 21:30 local time
(the Mac is set to Asia/Shanghai). It runs only the fixed daily command above and then the
independent audit (writing the root `validation_report.json`). It:

- fails closed unless the main checkout is on `main` with no tracked changes;
- picks the target session from the AkShare Sina trading calendar: today once 17:30 Shanghai has
  passed, otherwise the latest earlier session, so a late fire after sleep is safe;
- exits quietly when the state already holds the target session;
- refuses to run, and notifies, when the state date is not the session immediately before the
  target. It never bridges an evidence gap automatically; the 2026-07-21 cycle shows that the
  entrypoint itself will bridge one if invoked across missing sessions;
- retries the entrypoint up to 5 attempts, 30 minutes apart, only while the account and state
  hashes are unchanged; a failure after either changed stops immediately and notifies;
- logs to `outputs/automation/csi300_post_close/` (`<timestamp>.log`, `runs.jsonl`,
  `launchd.*.log`) and sends a macOS notification on every blocked, failed, or `FAILED`-audit run.

The 2026-10-17 all-cash bridge resolved that gap, so the job can run daily from the 2026-10-19
parent onward.

Install and uninstall commands are in `docs/operations.md` ("定时自动运行（launchd）"). Installed on
2026-10-20. Pause the Codex automation before installing so only one scheduler runs the
entrypoint.

## 2026-07-14 operational evidence

The early attempt and the 17:30 automation both failed closed without changing the formal account
or pipeline state.

Early attempt:

- current universe matched exactly 300 active historical members;
- daily collectors were corrected to request only membership intervals overlapping the requested
  dates, rather than all 439 five-year historical names;
- point-in-time factors completed 600 scopes with no failures;
- corporate actions initially had 47 transient JSON failures, then immutable retries reduced them
  to 10, 2, and finally zero (`retry-3`: 298 reused, 2 new successes);
- both current-day price sources still returned no 2026-07-14 rows during the early attempt;
- the latest execution price therefore remained 2026-07-13 and the freshness gate stopped before
  account/state mutation;
- `outputs/paper_trading/csi300_baseline/cycles/2026-07-14/` contains only
  `current_universe.csv` and `csi300_market_state.csv`; it does not contain a counted V2 manifest.

The scheduled 17:30 retry made further progress:

- signal price (`hfq`) and execution price (`none`) both completed 300/300 with no provider failures;
- signal output reached 530,982 rows under
  `csi300-signal-price-20260714-retry-1`;
- execution output completed under `csi300-execution-price-20260714-retry-1`;
- decision-report generation then raised
  `ValueError: factor trading-calendar hash does not match benchmark`;
- the preserved factor manifest records trading-calendar SHA-256
  `253a3106a1d443c96acea01c33aa4df9bf6d6523fff9a39a50550ad138467af4`;
- the refreshed benchmark later written at the same cycle path has SHA-256
  `ef236161aa021b98ef90e8da75707178ce3fb7822e8af7d46d0ca97177d56ab6`;
- no `cycle_manifest.json`, `data_health.json`, `paper_report.json`, `targets.csv`, or counted
  dashboard was created, and no audit ran;
- account SHA-256 remained
  `08fe931be6f62e3ff36e8f2bcd1c7c57d84aa0fd0ed86c49aba3ca91d90cde31`.

The root cause is in `scripts/run_csi300_post_close.py`. `_processed_stage_attempt()` currently
reuses a processed manifest when only the raw-parent manifest path and SHA-256 match. For the factor
stage, it does not also require the stored `trading_calendar_sha256` and `price_features_sha256` to
match the current benchmark and signal-feature artifacts. A same-date retry can therefore reuse a
valid immutable factor layer built against an earlier benchmark file, after that benchmark path has
been refreshed. The equality gate correctly detects the mismatch and must not be weakened.

The repair must add an exact same-date retry regression and make the factor processed-stage reuse
decision depend on every material input hash. A mismatch must allocate a fresh immutable
`-retry-N` processed run; never edit the preserved `2026-07-14` manifest or benchmark evidence.

## 2026-07-15 complete V2 cycle and active continuity blocker

The 2026-07-15 automation ran only `scripts/run_csi300_post_close.py` from a clean `main` at
`b4eabd16a6935149525d5f13d241db6c8efc4ebf`. It completed all raw and processed stages without a
failed scope and atomically committed a complete schema-version-2 paper cycle.

Data and signal evidence:

- signal-price and execution-price layers each contain 531,282 processed rows through 2026-07-15;
- the new factor manifest records the refreshed benchmark SHA-256
  `46589b1831ea3e4f26e15fa5978c06a86619e0ebb8ccfb15d56a5d4c9d2d49fa`, which exactly matches the
  2026-07-15 cycle benchmark;
- data health passed with price coverage `0.998916`, fundamental coverage `1.0`, and explicit
  price-volume-proxy coverage `0.984574`;
- fundamental and capital-flow score components both vary, with no stale observations and no
  detected future leakage;
- all 300 active constituents were scored; 16 passed the 70/0.8 entry gate;
- 42 tracked names fell more than 3%, so the fixed systemic-risk rule emitted `reduce` warnings for
  all 300 names and the target file remained empty.

Paper-account result:

- zero targets, trades, blocked orders, or applied corporate actions;
- actual and shadow NAV remained CNY 100,000;
- drawdown regime remained `normal` with zero observed paper drawdown;
- the account advanced from `2026-07-13` to `2026-07-15`, and pipeline state records the new
  account, cycle, benchmark, data-health, decision-report, and manifest hashes;
- the cycle is internally hash-consistent and passed approved-policy, daily-data-health,
  execution-integrity, maximum-drawdown, walk-forward, DQN-disabled, and live-disabled gates.

The post-commit audit is nevertheless `FAILED`. Its only integrity failure is:

```text
missing expected CSI 300 sessions: missing=['2026-07-14'] extra=[]
```

The auditor reports `valid_sessions=1` because it loaded one valid V2 manifest, but the missing
session makes `expected_session_continuity=false` and `reproducible_evidence=false`. Treat
2026-07-15 as preserved failed evidence, not as the first accepted day of the 40-session/56-day
window. Do not roll back the committed account/state, edit the cycle, or silently continue an
evidence clock that can no longer pass under the current anchor.

## Historical research result

The authoritative stable-HFQ formal comparison is
`outputs/csi300_research/hfq-formal-20260713/benchmark_comparison.json`.

- risk-controlled historical total return: approximately 118.30%;
- historical maximum drawdown: approximately 9.65%;
- historical Sharpe: approximately 1.71;
- positive CSI 300 excess return in the four reported segments.

The earlier QFQ result is rejected because future corporate actions rewrite the historical QFQ
scale and break immutable incremental reproducibility. These HFQ values are still historical
research, not a profit promise or live-trading approval.

## PnL dashboard

The local dashboard at
`outputs/paper_trading/csi300_baseline/hfq_formal_dashboard.html` now includes an interactive PnL
curve. It is the formal CSI 300 HFQ backtest, not the old STAR30 diagnostic and not accumulated
paper-trading performance.

The plotted interval is 2021-06-15 through 2026-07-13 with 1,231 daily points and CNY 100,000
normalized starting equity:

| Series | Ending equity | PnL | Total return |
|---|---:|---:|---:|
| Risk-controlled baseline | 218,295.88 | 118,295.88 | 118.30% |
| Unrestricted baseline | 215,321.64 | 115,321.64 | 115.32% |
| CSI 300 benchmark | 90,880.26 | -9,119.74 | -9.12% |

`pnl_curve.json` records the hashes of the two source run reports and benchmark CSV. The chart data
is embedded locally in the dashboard; Chart.js is pinned to version 4.5.1. When a daily V2 cycle
uses this optional formal curve, its manifest hash-binds the artifact and same-date replay verifies
it.

## Review completed for this handoff

The review covered the design and the full operational path:

- anchor creation and recursive raw/processed manifest verification;
- point-in-time decision inputs, coverage/variation/staleness/leakage health gates;
- active-date CSI 300 membership checks;
- failed-scope resume and all-empty price refresh behavior;
- baseline-only target policy and DQN rejection;
- D+1 open execution, T+1, suspension, limit rules, lot sizing, costs, dividend tax and rights policy;
- account staging, account-before/account-after hashes, pipeline-state alignment and same-date replay;
- V2 parent chain, input/output file hashes, NAV/target/trade/cost reconciliation and readiness gates;
- automation command, schedule and live-trading prohibition.

One important defect was found and fixed during this review: a direct V2 cycle could previously
omit corporate-actions or data-health, commit an account, and only fail later in the auditor. V2
now requires both inputs before running paper execution, and same-date replay re-verifies both.
Regression tests prove the canonical account stays byte-for-byte unchanged when either is missing.

Verification recorded before final merge:

- clean reviewed baseline: 424 passed, 2 skipped, 29 subtests passed;
- focused evidence-chain suite after the review fix: 46 passed, 2 subtests passed;
- final full suite after the review fix: 426 passed, 2 skipped, 31 subtests passed;
- Python compile check: passed;
- four V2 CLI help smoke checks: passed;
- whitespace/diff check: passed.

The later PnL dashboard series was merged at `5a6a9f2`. Its final verification recorded 443 passed,
2 skipped, and 31 unittest subtests passed, plus Ruff, Python compile, CLI, JavaScript syntax, and
artifact-reconciliation checks.

The 2026-07-16 read-only status review additionally verified:

- clean `main` matched `origin/main` at `b4eabd16a6935149525d5f13d241db6c8efc4ebf` after fetch;
- an independent audit reproduced `FAILED`, `valid_sessions=1`, and the missing `2026-07-14`
  continuity failure without mutating canonical state;
- focused post-close, auditor, and decision-report tests passed: 30 passed;
- the full suite passed: 443 passed, 2 skipped, and 31 unittest subtests passed;
- `git diff --check` passed;
- Ruff was not installed in the current virtual environment or `PATH`, so this review does not claim
  a fresh Ruff result; the previously recorded PnL-dashboard Ruff result remains historical
  verification only.

The 2026-07-27 V2 evidence repair verification recorded:

- focused post-close, anchor, auditor, and decision-report suites: 53 passed;
- full suite: 455 passed, 2 skipped, and 31 unittest subtests passed;
- Python compile and four V2 CLI help checks: passed;
- `git diff --check`: passed;
- Ruff was not installed in the active virtual environment or `PATH`, so no new Ruff result is
  claimed; and
- no provider-backed command ran, and no canonical account, state, anchor, cycle, dashboard, or
  report was modified.

## Known boundaries and next priorities

The four reported V2 code defects are repaired. The accepted evidence count remains zero, and every
item below still blocks any live-readiness claim:

1. The old epoch has permanent gaps and must be superseded explicitly. Delayed catch-up cycles, if
   needed to advance the canonical account, are operational repair evidence and must not be counted
   as fresh continuous validation.
2. AkShare upstream endpoints can return empty or non-JSON responses. Preserve immutable failures
   and retry; do not silently substitute current constituents or future data.
3. The auditor verifies the account hash chain, reported costs, allowed corporate actions, and full
   NAV reconciliation, but it does not independently replay every FIFO dividend-tax lot and every
   unapplied corporate-action decision from the prior account. Add an independent replay audit
   before considering a live broker.
4. The five staged outputs are committed with account replacement last. This protects canonical
   account progression on ordinary pre-commit errors, but an OS crash during the sequence can leave
   partial non-account outputs. The next run must rely on account/state/hash checks and fail closed;
   a future journal or directory-swap design would strengthen crash recovery.
5. Hash chaining is tamper-evident under preserved immutable artifacts; it is not a signed external
   timestamp. External/WORM retention or signed attestations would be required for stronger audit
   claims.
6. DQN backends remain behaviorally divergent. Do not pass a DQN report into paper exposure until
   the overlay is independently stable across walk-forward windows and seeds.

Immediate work order:

1. Done: repaired code merged; fresh epoch `anchor-20261016-epoch-2` created by the all-cash bridge.
2. After the 2026-10-19 close, run only `scripts/run_csi300_post_close.py --as-of 2026-10-19` with
   the fixed arguments above. If CSI announces a temporary adjustment for `601059.SH`, extend the
   membership file before running.
3. If the account is all cash after a future gap, use `scripts/bridge_csi300_paper_epoch.py`
   instead of a session-by-session catch-up; with open positions, keep the supersession plus
   non-counted catch-up procedure.
4. Count the new date only if the cycle is schema version 2, the fresh epoch parent and account
   hashes match, data health and execution reconcile, and the audit returns `COLLECTING` rather than
   `FAILED`. Record the first accepted date in `AGENTS.md` and this handoff.
5. Continue every trading session without gaps until at least 40 sessions and 56 calendar days.
   Investigate provider failures and evidence anomalies immediately; do not tune the strategy while
   collecting the fixed window.
6. After the complete paper window, evaluate net CSI 300 excess return, maximum drawdown, turnover,
   costs, sector/regime stability and every failed gate. `ELIGIBLE_FOR_REVIEW` still requires human
   review and never authorizes live trading.

## File map

- Project contract and status: `AGENTS.md`
- Project overview: `README.md`; operating instructions: `docs/operations.md`
- V2 design: `docs/superpowers/specs/2026-07-14-csi300-paper-evidence-v2-design.md`
- V2 implementation plan: `docs/superpowers/plans/2026-07-14-csi300-paper-evidence-v2.md`
- Daily CSI 300 entry: `scripts/run_csi300_post_close.py`
- Atomic paper cycle: `scripts/run_post_close_daily_cycle.py`
- Decision-health gate: `scripts/build_daily_decision_report.py`
- Paper execution: `scripts/run_daily_paper_trading.py`
- Anchor support: `scripts/initialize_csi300_paper_validation.py`
- Audit CLI: `scripts/audit_csi300_paper_validation.py`
- Evidence policy/anchor library: `src/fintech_quant/execution/paper_evidence.py`
- Auditor implementation: `src/fintech_quant/reports/paper_validation.py`
- PnL curve builder: `src/fintech_quant/reports/pnl_curve.py`
- PnL curve CLI: `scripts/build_pnl_curve.py`
- Formal PnL data: `outputs/csi300_research/hfq-formal-20260713/pnl_curve.json`
- Formal dashboard: `outputs/paper_trading/csi300_baseline/hfq_formal_dashboard.html`
- Canonical account/state: `data/paper/csi300_baseline/`
- Counted/partial cycle outputs: `outputs/paper_trading/csi300_baseline/cycles/`
- Latest complete V2 cycle: `outputs/paper_trading/csi300_baseline/cycles/2026-07-15/`
- Latest authoritative audit: `outputs/paper_trading/csi300_baseline/cycles/2026-07-15/validation_report.json`
- Preserved 2026-07-14 factor manifest:
  `data/diagnostics/processed-factor-runs/csi300-factor-20260714/manifest.json`
- Automation definition (Codex, paused): `/Users/yakou/.codex/automations/csi300/automation.toml`
- Scheduled wrapper: `scripts/run_scheduled_csi300_post_close.py`
- launchd job: `deploy/launchd/com.vibetrading.csi300-post-close.plist`

## Suggested prompt for a new conversation

> Read `/Users/yakou/Desktop/Vibe-Trading/AGENTS.md` and
> `/Users/yakou/Desktop/Vibe-Trading/handoff.md` completely. Verify clean `main` equals
> `origin/main`, then inspect the canonical CSI 300 account, pipeline state, latest V2 cycle and
> cycle-local validation report. Reproduce the documented 2026-07-14 same-date processed-factor
> reuse bug with a regression test, then make factor reuse bind the raw-parent, trading-calendar,
> and signal-feature hashes without weakening the equality gate or editing immutable artifacts.
> Preserve the failed 2026-07-15 cycle, implement an explicit hash-linked validation-epoch
> supersession from the committed account/state, unify the latest-audit reference, and add a
> pre-commit continuity check. Use only the fixed daily CSI 300 entrypoint for the next eligible
> post-close run, keep DQN/live trading disabled, run full verification, and do not count a date
> unless the fresh audit returns `COLLECTING` or `ELIGIBLE_FOR_REVIEW` with all integrity gates
> passing.
