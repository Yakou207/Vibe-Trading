# PnL Curve Dashboard Design

## Purpose

Add an interactive cumulative PnL line chart to the existing CSI 300 research dashboard so the
authoritative HFQ backtest result can be understood visually. The chart compares the
risk-controlled baseline, the unrestricted scored baseline, and CSI 300 over the same dates and
the same CNY 100,000 starting-equity convention.

The chart reports historical research evidence only. It does not represent live or continuously
accumulated paper-account PnL, and it does not change stock selection, execution, risk control, or
account state.

## Constraints

- Use only the accepted HFQ formal backtest artifacts. The rejected incremental-QFQ result must
  never be used as a chart input.
- Preserve the existing KPI cards, benchmark table, paper-account summary, and health status.
- Do not parse the two approximately 600 MB run reports in the browser or on every dashboard
  refresh.
- Do not fetch curve data over the network. The only network dependency is the pinned chart
  renderer selected by the user.
- Fail visibly when curve data is missing, inconsistent, or cannot be rendered. Never fabricate,
  forward-fill, or silently drop a required date.
- Keep dashboard generation deterministic and preserve the V2 evidence manifest's input/output
  hash guarantees.

## Chosen Approach

Generate one small, immutable-style `pnl_curve.json` artifact from the authoritative baseline
report, risk-controlled report, and CSI 300 benchmark series. Dashboard generation embeds that
artifact directly into the HTML and uses Chart.js 4.5.1 from the pinned jsDelivr UMD URL to render
the chart.

This keeps the browser payload small and auditable while retaining interactive hover details. It
also keeps the dashboard usable as a local file: no HTTP server and no request for curve data are
required. Only the JavaScript renderer requires network access.

## Curve Artifact

A focused report module and CLI command build `pnl_curve.json` once per formal research run. The
builder reads:

- the unrestricted baseline `run_report.json` equity curve;
- the risk-controlled baseline `run_report.json` equity curve; and
- the exact CSI 300 benchmark CSV referenced by the formal run manifest.

The output schema is compact and uses one shared date array:

```json
{
  "schema_version": 1,
  "initial_equity": 100000.0,
  "dates": ["2021-06-15", "2021-06-16"],
  "series": {
    "risk_controlled": {
      "label": "Risk-Controlled",
      "equity": [100000.0, 100120.0],
      "pnl": [0.0, 120.0],
      "return": [0.0, 0.0012]
    },
    "baseline": {
      "label": "Baseline",
      "equity": [100000.0, 100080.0],
      "pnl": [0.0, 80.0],
      "return": [0.0, 0.0008]
    },
    "csi300": {
      "label": "CSI 300",
      "equity": [100000.0, 99950.0],
      "pnl": [0.0, -50.0],
      "return": [0.0, -0.0005]
    }
  },
  "inputs": {}
}
```

`inputs` records the resolved source path, byte count, and SHA-256 value for all three source
files. Dates must be strictly increasing and unique. Both strategy reports must have identical
dates, and the benchmark must contain every strategy date. A mismatch fails artifact generation.

Each series is normalized to CNY 100,000 on the first shared date:

- strategy equity is `100000 * reported_equity / first_reported_equity`;
- benchmark equity is `100000 * index_close / first_index_close`;
- PnL is normalized equity minus `100000`; and
- return is PnL divided by `100000`.

The builder uses full daily observations. The expected five-year payload is only a few thousand
numeric values, so downsampling would add complexity and reduce auditability without a material
benefit. Numeric rounding is fixed so repeated builds from unchanged inputs are byte-stable.

## Dashboard Integration

`build_research_dashboard` accepts the curve artifact as an optional input. The dashboard CLI and
post-close cycle accept a corresponding optional `--pnl-curve` path. If no explicit path is
provided, the CSI 300 wrapper may use `pnl_curve.json` next to the selected formal comparison when
that file exists; otherwise the dashboard shows a clear unavailable state.

The artifact is serialized into a non-executable JSON script element in the generated HTML. The
chart script reads only this embedded payload. It does not issue `fetch`, XHR, or filesystem
requests.

The PnL chart appears after the headline KPI cards and before the benchmark-comparison table. It
uses:

- risk-controlled baseline: teal;
- unrestricted baseline: blue;
- CSI 300: amber;
- a visible zero-PnL reference line;
- CNY formatting on the Y axis;
- date labels with automatic skipping on the X axis; and
- a tooltip containing date, cumulative PnL, normalized equity, and cumulative return.

Lines have no persistent point markers so the five-year chart remains legible, while the hovered
observation receives a marker. The canvas is responsive with a bounded height and retains the
existing dashboard's static-file layout.

## Dependency and Fallback Behavior

The HTML loads the pinned renderer from:

`https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js`

Pinning prevents an unreviewed future Chart.js release from changing the dashboard. The project
does not download, vendor, or execute any other external resource.

If the curve artifact is absent or fails schema validation, dashboard generation retains the
existing report and shows `PnL curve unavailable` with a short reason. If the CDN cannot load,
the chart region shows `Chart renderer unavailable`; all cards and tables remain readable. A
renderer failure does not alter the underlying PnL artifact or any research metric.

## Evidence-Chain Handling

When a post-close cycle uses a curve artifact, its V2 cycle manifest records the artifact path,
size, and SHA-256 as a material dashboard input. Same-date replay must verify the same curve hash.
The generated dashboard remains an output hash in the existing atomic commit group.

The curve artifact is reporting-only: it is not an input to targets, fills, drawdown state, paper
NAV, or readiness-gate calculations. Changing it changes the dashboard hash and therefore must be
visible in the evidence chain, but cannot change a trading decision.

## Current Formal Output

After implementation, the current accepted artifacts will be used to generate:

- `outputs/csi300_research/hfq-formal-20260713/pnl_curve.json`; and
- `outputs/paper_trading/csi300_baseline/hfq_formal_dashboard.html`.

The generated output files remain run artifacts rather than source-controlled fixtures. Source
code, tests, and this design are committed. The dashboard's existing displayed headline metrics
must continue to match the authoritative formal comparison exactly.

## Error Handling

- Missing source files, empty curves, duplicate dates, non-finite values, non-positive initial
  equity/index levels, strategy-date disagreement, or a missing benchmark date fail curve
  generation.
- A malformed optional curve artifact does not produce a misleading partial chart. Dashboard
  generation presents the unavailable state instead.
- A supplied curve artifact whose recorded source hashes no longer match its files is rejected by
  the artifact-building or evidence-validation path rather than silently rebuilt.
- No interpolation, forward filling, date truncation, or substitution with paper-account NAV is
  allowed.

## Testing Strategy

- Unit tests verify strict date alignment, CNY 100,000 normalization, PnL/return calculations,
  deterministic rounding, source hashes, and each fail-closed input condition.
- Dashboard tests verify the pinned Chart.js URL, chart canvas, embedded JSON, all three labels,
  tooltip fields, zero reference, and both missing-data and renderer fallbacks.
- CLI tests verify explicit curve generation and dashboard input paths.
- Post-close tests verify that a supplied or inferred curve artifact is hash-bound in the V2
  manifest and that same-date replay rejects a changed artifact.
- Regression tests verify that dashboards without a curve remain valid and that no trading or
  readiness calculation consumes the new reporting input.
- Final verification regenerates the authoritative local dashboard, checks its displayed totals
  against the formal comparison, performs structural HTML checks, and visually reviews the chart
  after refreshing the existing local dashboard tab.

## Scope Boundaries

This change does not rerun or tune the strategy, change the 35/25/25/15 scoring model, enable DQN,
connect a broker, mutate the paper account, or claim future profitability. It adds a transparent
view of already accepted historical evidence.
