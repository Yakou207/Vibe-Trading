# Vibe-Trading CSI 300 handoff

Last reviewed: 2026-07-15 15:19 Asia/Shanghai
Repository: `/Users/yakou/Desktop/Vibe-Trading`
Remote: `https://github.com/Yakou207/Vibe-Trading.git`
Reviewed commit: `5a6a9f2f5f6f940f42cdc27023f171a5f78b29e8` (`main == origin/main` before this documentation update)

## Resume here

1. Read `AGENTS.md` and this file completely.
2. Run `git status --short`, `git branch --show-current`, `git rev-parse HEAD`, and
   `git rev-parse origin/main`. Work only from a clean `main` that matches `origin/main`.
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
- the canonical account is still dated `2026-07-13`;
- cash is `100000.0`, positions are empty, and no fresh V2 session has been counted;
- validation status is `NO_EVIDENCE` with `valid_sessions=0`;
- `live_trading_authorized=false` and DQN paper exposure is disabled;
- the weekday 17:30 Asia/Shanghai automation is active;
- the 2026-07-14 automation fetched both price layers successfully, then failed closed because the
  factor trading-calendar hash did not match the refreshed benchmark;
- the immediate task is to diagnose that hash mismatch and complete the first fresh, fully audited
  V2 paper cycle, then accumulate at least 40 valid sessions over at least 56 calendar days.

## Canonical state and hashes

These values were rechecked during this review:

| Artifact | State | SHA-256 |
|---|---|---|
| `data/paper/csi300_baseline/account.json` | `last_processed_date=2026-07-13`, cash 100000, no positions | `08fe931be6f62e3ff36e8f2bcd1c7c57d84aa0fd0ed86c49aba3ca91d90cde31` |
| `data/paper/csi300_baseline/pipeline_state.json` | `last_successful_as_of=2026-07-13` | `5d1ae61c0f2d68aa6ba3bed89270113b8aea5af7aa354ff97c138a5121e03f7a` |
| `data/paper/csi300_baseline/validation/anchor-20260713/anchor_manifest.json` | non-counted anchor | `13c2ead2826740a7426e9ffb557b23219c8abfa3ab3de73d174be9ab9c0c3a2a` |
| `outputs/paper_trading/csi300_baseline/validation_report.json` | `NO_EVIDENCE`, zero valid sessions | `23209bf404d408f076226050804dcc786d75f266f62f747d5cd0328f06ebccc2` |
| `outputs/csi300_research/hfq-formal-20260713/pnl_curve.json` | 1,231 formal CSI 300 comparison points | `abb86cff7adc98fcfb09a0a21da4fe610a9b7a671f1a927e7bdf0290f7f64107` |
| `outputs/paper_trading/csi300_baseline/hfq_formal_dashboard.html` | formal backtest dashboard with PnL curve | `147addb8a7fe9f225cce0ce642a9986c378ede58f4aeae2804b99534e81daecc` |

The validation-report hash can change after an intentional audit rerun even if its semantic status
does not. Account and pipeline-state hashes must not change on a pre-commit failure.

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
- the preserved factor manifest points to the benchmark ending on 2026-07-13 with SHA-256
  `56e4829e87a52ad2d3eb75b76c749bc79c634d1716bfbcdd7ac563ca6e25f6f4`;
- no `cycle_manifest.json`, `data_health.json`, `paper_report.json`, `targets.csv`, or counted
  dashboard was created, and no audit ran;
- account SHA-256 remains
  `08fe931be6f62e3ff36e8f2bcd1c7c57d84aa0fd0ed86c49aba3ca91d90cde31`.

Do not bypass the calendar-hash gate or edit an immutable manifest. Determine whether the daily
factor layer must be rebuilt against the refreshed benchmark artifact, add a failing regression
test for the exact mismatch, then rerun only the fixed post-close entrypoint.

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

One Important defect was found and fixed during this review: a direct V2 cycle could previously
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

## Known boundaries and next priorities

These are not blockers for continuing paper evidence, but they block any live-readiness claim:

1. No real post-anchor V2 session has passed yet. The auditor's counted-cycle behavior is covered by
   fixed integration tests, not by a real multi-day evidence chain.
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

1. Reproduce and diagnose the 2026-07-14 factor/benchmark trading-calendar hash mismatch without
   changing the account, pipeline state, or immutable manifests.
2. Add a regression test, make the minimum repair, and rerun the fixed post-close entrypoint for a
   fresh eligible session. Do not reconstruct the daily stages manually.
3. If the first V2 cycle succeeds, verify `cycle_manifest.json`, `data_health.json`,
   `paper_report.json`, targets, dashboard, account/state dates, parent hash, and audit status.
4. Record the first counted date in `AGENTS.md` and this handoff only after independent audit passes.
5. Continue every trading session without gaps until at least 40 sessions and 56 calendar days.
6. Investigate provider failures and evidence anomalies immediately; do not tune the strategy while
   input completeness or execution reconciliation is unresolved.
7. After the complete paper window, evaluate net CSI 300 excess return, maximum drawdown, turnover,
   costs, sector/regime stability and every failed gate. `ELIGIBLE_FOR_REVIEW` still requires human
   review and never authorizes live trading.

## File map

- Project contract and status: `AGENTS.md`
- Operating instructions: `README.md`
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
- Automation definition: `/Users/yakou/.codex/automations/csi300/automation.toml`

## Suggested prompt for a new conversation

> Read `/Users/yakou/Desktop/Vibe-Trading/AGENTS.md` and
> `/Users/yakou/Desktop/Vibe-Trading/handoff.md` completely. Verify clean `main` equals
> `origin/main`, then inspect the canonical CSI 300 account, pipeline state, latest V2 cycle and
> validation report. First reproduce and repair the documented factor/benchmark trading-calendar
> hash mismatch with a regression test. Preserve immutable manifests, use only the fixed daily CSI
> 300 entrypoint for the operational rerun, keep DQN/live trading disabled, run full verification,
> and commit/push through a `codex/` branch before merging.
