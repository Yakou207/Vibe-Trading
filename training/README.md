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

Run resumable DQN continual training:

```bash
PYTHONPATH=src python3 training/run_dqn_continual_training.py --resume latest
```

For the first run, or when deliberately starting over, use:

```bash
PYTHONPATH=src python3 training/run_dqn_continual_training.py --fresh
```

Default outputs:

- `data/models/dqn/manifest.json`
- `data/models/dqn/checkpoints/<checkpoint_id>/model.pt`
- `data/models/dqn/checkpoints/<checkpoint_id>/target_model.pt`
- `data/models/dqn/checkpoints/<checkpoint_id>/optimizer.pt`
- `data/models/dqn/checkpoints/<checkpoint_id>/replay_buffer.pkl`
- `data/models/dqn/checkpoints/<checkpoint_id>/scaler.json`
- `data/models/dqn/checkpoints/<checkpoint_id>/config.json`
- `data/models/dqn/checkpoints/<checkpoint_id>/training_state.json`
- `data/models/dqn/checkpoints/<checkpoint_id>/metrics.json`

Only the latest 10 checkpoints are retained by default.
