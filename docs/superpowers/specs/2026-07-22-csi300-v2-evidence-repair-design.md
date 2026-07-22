# CSI 300 V2 Evidence Repair Design

## Purpose

Repair the four blocking defects recorded in `handoff.md` without editing or deleting the
preserved 2026-07-14 partial evidence, the original validation anchor, or the failed 2026-07-15
V2 cycle:

1. same-date factor processing may reuse an output built from stale material dependencies;
2. the current validation epoch cannot recover from its permanent 2026-07-14 session gap;
3. the pipeline discovers session-continuity gaps only after committing paper-account state; and
4. the root validation report and pipeline state can disagree with the latest cycle-local audit.

The repair must keep the approved baseline-only policy unchanged. It must not tune strategy
thresholds, enable DQN exposure, authorize live trading, or weaken the anchor-to-latest trading
session continuity rule.

## Chosen Approach

Extend the existing immutable evidence model with an explicit superseding validation epoch and a
single active evidence-parent reference in pipeline state. This keeps the current directory layout
and daily entrypoint while making epoch changes deliberate and auditable.

The rejected alternatives are:

- using a separate cycle root for every epoch, which would require broader command, automation,
  dashboard, and migration changes; and
- treating continuity as beginning at the first counted cycle rather than the anchor, which would
  weaken the current fail-closed policy and hide missed sessions.

## Processed-Factor Reuse

`_processed_stage_attempt()` will accept an optional mapping of material dependency hashes in
addition to the raw-parent manifest. A completed processed run is reusable only when its manifest
request contains the same raw-parent path and hash plus every supplied dependency hash.

The factor stage will bind:

- `parent_manifest_sha256` for the raw point-in-time factor manifest;
- `trading_calendar_sha256` for the current cycle benchmark; and
- `price_features_sha256` for the current signal-feature artifact.

Price and corporate-action stages continue to use only their raw-parent dependency. When any
factor dependency differs, the pipeline allocates the next unused immutable `-retry-N` processed
run and invokes `build_point_in_time_factors.py`. The decision-report equality gate remains
unchanged.

## Validation-Epoch Supersession

`initialize_csi300_paper_validation.py` will gain an explicit supersession option. Normal
initialization will continue to reject a state that already contains a validation anchor.
Supersession will require and verify the current anchor, current account/state alignment, and the
latest committed cycle reference when one exists.

The new non-counted anchor will:

- snapshot the current canonical account, pipeline state, formal run manifest, comparison, and
  benchmark using the existing validation rules;
- use a collision-free immutable epoch directory;
- record verified file references to the superseded anchor, latest committed cycle, and latest
  validation report when available; and
- remain baseline-only, non-counted, DQN-disabled, and live-trading-disabled.

After the new anchor verifies successfully, pipeline state will atomically set both
`validation_anchor` and a new explicit `evidence_parent` to that anchor. Historical
`cycle_manifest` and validation references remain in the snapshotted old state and the new
anchor's supersession record. The next successful cycle replaces the active `evidence_parent`
with its own cycle manifest.

The auditor will treat cycles dated on or before the active anchor as historical evidence outside
the new epoch. Every later cycle must still form one strict, increasing chain from the active
anchor.

## Pre-Commit Session Continuity

After the current benchmark is refreshed, but before `run_post_close_daily_cycle.py` can mutate the
paper account, the daily entrypoint will verify the active epoch's session sequence.

It will derive the active parent date from the verified anchor or latest active cycle, read CSI 300
trading dates from the refreshed benchmark, and require the requested `as_of` date to be exactly
the next benchmark session. Weekends and exchange holidays therefore do not create false gaps.
Missing, duplicate, out-of-order, or non-session dates fail before paper execution and leave the
canonical account and pipeline state byte-for-byte unchanged.

This check prevents predictable continuity failures. The post-commit deterministic auditor remains
authoritative for the complete evidence chain and all other validation gates.

## Canonical Latest Audit

The cycle-local `validation_report.json` remains the immutable report for that audit run. After the
report is generated and validated, the daily entrypoint will atomically copy the same bytes to the
root `outputs/paper_trading/csi300_baseline/validation_report.json` and record a verified
`validation_report` reference in pipeline state.

Both a newly completed cycle and a same-date replay will refresh the root copy and the state
reference. The returned automation summary will use the status from this same report. A failed
audit subprocess will not fabricate or advance a validation reference.

The static cycle dashboard will not embed the current audit status because that would introduce a
hash cycle: the cycle manifest hashes the dashboard while the audit hashes and verifies the cycle
manifest. The adjacent cycle-local report, its byte-identical root mirror, and the pipeline-state
reference are the canonical status surfaces.

## Error Handling and Atomicity

- Existing manifests, anchors, cycles, and reports are never edited or deleted.
- Dependency mismatch creates a new processed run rather than repairing an old manifest.
- Supersession writes and verifies the new anchor before atomically updating pipeline state; a
  failure removes only the incomplete new anchor directory.
- Session-continuity failure happens before paper execution and preserves account/state bytes.
- Root audit publication uses an atomic file replacement. Pipeline state references it only after
  the cycle-local and root reports have been verified as byte-identical.
- Post-commit auditor failure preserves the committed paper cycle, consistent with the existing V2
  contract, but leaves the latest-audit reference unchanged.

## Testing and Verification

Tests will be written before production changes and must demonstrate the intended failure first.
Coverage will include:

- the exact 2026-07-14 retry shape: unchanged raw-factor parent, refreshed benchmark and/or signal
  features, and a completed stale processed-factor run;
- reuse when all material factor hashes match and `-retry-N` allocation when either hash differs;
- superseding-anchor creation, verified references to preserved evidence, atomic state transition,
  and rollback on failure;
- auditing a new epoch while ignoring preserved cycles dated on or before its anchor;
- pre-commit rejection of a skipped CSI 300 session with unchanged account/state and no paper-cycle
  invocation;
- success across weekends or holidays when the benchmark contains no intervening session;
- byte-identical cycle-local and root audit reports plus matching pipeline-state references; and
- same-date replay refreshing only audit status without changing the paper account.

Verification will run the focused post-close, anchor, auditor, and decision-report suites, followed
by the full test suite, Python compile checks, CLI help checks, available linting, and
`git diff --check`. No provider-backed post-close cycle will be run as part of the code repair.

## Success Criteria

The repair is complete when all tests and checks pass and the code guarantees that:

- stale material factor dependencies cannot be reused;
- an operator can explicitly start a hash-linked validation epoch without altering old evidence;
- a known session gap cannot commit account or state changes; and
- cycle-local, root, pipeline-state, and command-result audit status all refer to the same report.
