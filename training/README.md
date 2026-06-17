# Training Experiments

This folder contains user-facing experiment runners for reinforcement-learning
research. Package code stays under `src/fintech_quant/training/`; this folder is
for repeatable training runs and report generation.

Run RL stability training:

```bash
PYTHONPATH=src python3 training/run_rl_stability_report.py
```

Outputs:

- `outputs/rl_stability_report.json`
- `outputs/rl_stability_report.html`

