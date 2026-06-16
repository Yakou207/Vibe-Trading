# Data Quality Review

Generated after collecting one year of AkShare daily data for 30 STAR Market
stocks.

## Dataset Grain

- Source file: `data/processed/akshare_research_daily.csv`
- Intended grain: one row per `代码` and trading `date`
- Current symbol count: 30
- Current row count: 6,848
- Date range: 2025-06-16 to 2026-06-16

## Checks Performed

- Required fields populated: `代码`, `名称`, `date`, `open`, `high`, `low`,
  `close`, `volume`
- Duplicate `(代码, date)` keys
- OHLC consistency: `high >= open/low/close` and `low <= open/high/close`
- Negative volume rows
- Date parsing and future-date checks
- Per-symbol freshness versus the dataset max date
- Sample cross-source comparison against Yahoo Finance for recent closes and
  volumes

## Findings

- Core structural checks passed: no duplicate symbol-date keys, no required
  field gaps, no OHLC violations, and no negative volume rows.
- Two STAR Market symbols have short history because they listed in 2026:
  `sh688808` starts on 2026-04-24 and `sh688820` starts on 2026-04-21. This is
  expected history coverage, not a failed download.
- High prices for `sh688808`, `sh688498`, and `sh688256` are not local
  processing artifacts. AkShare historical rows, AkShare/Sina spot rows, and
  Yahoo Finance samples agree on the same order of magnitude for recent closes.
- Yahoo Finance returned an impossible negative close for `688808.SS` on
  2026-06-16 while matching AkShare on volume and earlier closes. For this
  symbol/date, prefer AkShare/Sina over Yahoo.

## Use Guidance

- Use the dataset for early feature engineering and baseline strategy work.
- Do not yet use it for production-grade model training without adding a
  refresh/freshness gate and a source reconciliation step.
- Keep `outputs/data_quality_report.json` as the latest machine-readable audit
  output after each collection run.
