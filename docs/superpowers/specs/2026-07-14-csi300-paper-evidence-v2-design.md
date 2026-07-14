# CSI 300 Paper Evidence V2 Design

## Purpose

Upgrade the baseline-only CSI 300 paper-trading loop from operationally atomic daily files to a
tamper-evident validation record that can support the project's eight-week live-readiness gate.
The system may conclude only that a strategy is `ELIGIBLE_FOR_REVIEW`; it must never connect a
broker, place a real order, or enable live trading automatically.

The first counted cycle is the first fresh successful session after the 2026-07-13 bootstrap. The
bootstrap and the rejected incremental-`qfq` run never count as paper evidence.

## Constraints

- The scored 35/25/25/15 multi-factor baseline remains the only paper stock-selection engine.
- DQN remains diagnostic-only and must be absent from counted paper cycles.
- Entry score remains 70, confidence remains 0.8, and maximum stock weight remains 8%.
- Portfolio exposure remains reduced at 8% drawdown, liquidation starts at 9%, and the validation
  limit remains 10%.
- Signal prices use stable `hfq`; execution and mark-to-market prices use `adjust=none`.
- Paper costs use 0.03% commission, CNY 5 minimum commission, date-specific sell stamp duty,
  individual dividend tax, and 0.05% slippage. The current post-close default of zero slippage is
  a parity defect and must be corrected before the first counted cycle.
- Rights issues use the explicit `do_not_subscribe` policy.
- Existing immutable data manifests and point-in-time health gates remain authoritative.
- V1 cycle manifests may be inspected but never count toward V2 continuity.

## Chosen Approach

Use a small JSON/CSV evidence layer on top of the existing immutable file architecture. This is
stronger than merely scanning V1 outputs because every decision input becomes hash-bound, while
remaining simpler and more reviewable than introducing an event database.

The evidence layer has three parts:

1. An immutable bootstrap anchor that snapshots the canonical account and pipeline state before
   the evidence clock starts.
2. A schema-version-2 cycle manifest that binds the prior evidence record, every material input,
   the policy configuration, the complete paper-account transition, and every daily output.
3. A deterministic auditor that verifies the chain and writes the current eight-week gate report.

## Bootstrap Anchor

`scripts/initialize_csi300_paper_validation.py` creates one immutable directory under the selected
validation root. It copies the account and pipeline state instead of referencing mutable canonical
paths. It also copies or hash-binds the authoritative HFQ formal comparison and benchmark series.

The anchor manifest records:

- `schema_version: 1` and `kind: "paper_validation_anchor"`;
- bootstrap `as_of`, creation timestamp, and Git SHA;
- `counts_toward_evidence: false`;
- immutable snapshot paths, byte counts, and SHA-256 values;
- the account equity and drawdown regime at the boundary;
- the four raw/processed data-manifest references already verified by pipeline state;
- the formal comparison and benchmark references;
- the complete fixed policy configuration;
- `live_trading_enabled: false` and `dqn_exposure_enabled: false`.

Creation fails if the account and pipeline-state dates differ, the state manifests fail recursive
verification, the signal manifest is not `hfq`, execution prices are not unadjusted, the formal
data-health result did not pass, or the target directory already exists. After creating and
verifying the anchor, the command atomically adds its path and hash to canonical pipeline state;
it does not advance `last_successful_as_of` or mutate the account.

## Cycle Manifest V2

`scripts/run_post_close_daily_cycle.py` writes a V2 manifest inside its existing staging and file
lock. The manifest is committed in the same atomic group as targets, paper report, dashboard, and
account.

Each V2 manifest records:

- `schema_version: 2`, `kind: "paper_trading_cycle"`, `as_of`, and Git SHA;
- an `evidence_parent` path/hash pointing to the bootstrap anchor for the first cycle or the prior
  V2 cycle manifest thereafter;
- `account_before_sha256` and `account_after_sha256`;
- hashes for the decision report, unadjusted execution-price snapshot, current-universe snapshot,
  benchmark series, formal comparison, corporate-action ledger, and data-health report;
- optional information-health, walk-forward, or diagnostic references when supplied;
- every policy and cost parameter that affects targets or fills;
- explicit `signal_adjust: "hfq"`, `execution_adjust: "none"`,
  `dqn_exposure_enabled: false`, and `live_trading_enabled: false`;
- output hashes for targets, the full paper report/account snapshot, and dashboard.

The writer verifies every referenced file before commit. It also verifies that the account object
embedded in the paper report serializes to `account_after_sha256`. A DQN report or non-empty DQN
overlay makes a counted V2 cycle invalid rather than silently downgrading the gate.

`scripts/run_csi300_post_close.py` resolves the evidence parent from pipeline state, passes all
explicit inputs to the atomic cycle, and carries the anchor plus latest cycle reference into the
next state. The first V2 cycle must chain to the anchor; later cycles must chain to the exact prior
manifest and account hash.

## Validation Auditor

`scripts/audit_csi300_paper_validation.py` reads the anchor and all V2 cycle manifests oldest to
newest. Core calculation and validation live in a focused module so unit tests do not need to
spawn subprocesses.

The auditor performs these checks:

1. Verify anchor, manifest, input, output, and embedded-account hashes.
2. Verify unique increasing dates and that every manifest's evidence parent is the immediately
   preceding record.
3. Verify each `account_before_sha256` equals the previous record's account-after hash.
4. Verify every expected CSI 300 benchmark trading session after the anchor has exactly one V2
   cycle; weekends and exchange holidays are not expected sessions.
5. Verify every daily health report passed, its date is current, and it reports zero stale-factor
   and future-leakage observations.
6. Verify the fixed policy configuration and confirm DQN/live flags remain false.
7. Reconcile daily NAV, account date, targets, trades, blocked orders, corporate actions, and
   full account snapshot. Suspension, limit-up, limit-down, and T+1 blocks are reported as modeled
   market constraints. Missing prices, insufficient cash caused by sizing, unknown block reasons,
   broken account transitions, or missing artifacts are validation failures.
8. Compute actual paper total return, benchmark return, excess return, daily maximum drawdown,
   turnover, modeled costs, trade count, and constraint-block counts from the counted interval.
9. Re-verify that the anchored formal comparison has positive candidate benchmark excess return
   in every reported walk-forward segment.

The auditor writes a deterministic JSON report with one of four statuses:

- `NO_EVIDENCE`: no valid V2 cycle exists after the anchor.
- `COLLECTING`: integrity passes but duration or performance gates are not yet satisfied.
- `FAILED`: an integrity, continuity, risk, data, execution, or performance gate fails.
- `ELIGIBLE_FOR_REVIEW`: every gate passes; this is not permission to trade live.

## Gate Definitions

Eligibility requires all of the following at the same audit point:

- at least 40 valid paper sessions;
- an inclusive counted span of at least 56 calendar days;
- no missing expected CSI 300 sessions between the first and latest counted cycles;
- actual paper return after modeled costs strictly greater than the CSI 300 return;
- paper maximum drawdown no greater than 10%;
- positive candidate-vs-CSI-300 excess return in every anchored formal walk-forward segment;
- all daily data-health and reproducibility checks passing;
- no unexplained execution, reconciliation, manifest, or account-chain anomaly;
- unchanged approved policy, no DQN exposure, and no live broker activity.

`COLLECTING` is appropriate while the evidence window is too short or while performance is below a
target without any integrity failure. `FAILED` is reserved for broken evidence or a completed
minimum window that violates a mandatory gate. Reports always show each gate independently so a
later valid window can be evaluated without hiding earlier failures.

## Operational Flow

1. Initialize and verify the non-counted anchor once.
2. At each post-close run, refresh immutable data and pass existing health gates.
3. Execute the previous close's targets using the current session's open, then mark NAV at close.
4. Generate current-close targets and commit the account plus V2 cycle atomically.
5. Run the auditor. Evidence-report failure never erases a committed paper execution; it raises an
   operational alert and prevents the cycle from advancing validation eligibility until repaired.
6. The weekday automation reports cycle outcome and current gate status. It never changes broker
   connectivity.

This separation matches real operations: an executed transaction cannot be rolled back merely
because downstream reporting failed, while reporting failure must remain visible and must block
promotion.

## Error Handling

- Pre-commit input, policy, manifest, dashboard, or account-reconciliation failures leave the
  canonical account and cycle outputs byte-for-byte unchanged.
- Duplicate dates with the same verified V2 manifest are idempotent.
- Duplicate dates with missing or inconsistent evidence fail closed.
- A post-commit audit error leaves the already committed paper record intact, exits visibly, and
  keeps the readiness status non-eligible.
- V1 manifests, bootstrap reports, partial directories, and manually edited artifacts never count.
- The auditor does not repair, backfill, or silently skip evidence.

## Testing Strategy

- Unit tests cover anchor creation, immutable copies, hash tampering, policy parity, parent-chain
  order, account-hash continuity, trading-calendar gaps, 40-session/56-day boundaries, return and
  drawdown calculations, DQN/live rejection, allowed market blocks, and unexplained anomalies.
- CLI tests cover atomic rollback, same-date idempotence, V1 non-counting, audit output statuses,
  and exact 0.05% paper slippage propagation.
- A fixed two-session integration fixture proves D targets execute at D+1 open and both V2 cycles
  form one valid chain.
- Full regression, compile checks, CLI help, diff checks, and a real bootstrap-anchor dry run are
  required before merge.
- The first real counted session requires a V2 manifest, passing data health, a matching account
  hash, and a successful audit. No historical bootstrap date is retroactively counted.

## Scope Boundaries

This phase does not tune scores, add factors, approve DQN, integrate QMT/miniQMT, place real orders,
or claim future profitability. It provides the evidence needed for a later human decision about
whether live-broker engineering should even be considered.
