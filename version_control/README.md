# Version Control Notes

This folder records project-level checkpoints and reproducibility notes for the
quant research system.

## Pre-Optimization Backup

- Backup branch: `backup/pre-dashboard-20260618`
- Backup tag: `backup/pre-dashboard-20260618`
- Backup commit: `911bb2d94727ae100e4f550383d88cab704b3076`
- Working branch for this optimization: `codex/quant-dashboard-foundation`

## Local Commands

```bash
make check-env
make test
make dashboard
```

## Dashboard Scope

The current dashboard is a local research dashboard. It reads local artifacts in
`outputs/` and `data/processed/` and is meant to support strategy comparison,
factor review, and risk monitoring before any live trading integration.

## Reproducibility Rule

Research outputs under `data/`, `outputs/`, and `data/models/` are ignored by
Git. Code that generates those files must live in tracked modules or scripts
before a result is considered reproducible.
