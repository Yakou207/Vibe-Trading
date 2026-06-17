# RL v2 Stability Training Design

## Purpose

Improve the Q-learning research loop so it evaluates reinforcement-learning
stability instead of relying on one random run. The goal is not supervised
learning and not manual rule tuning; it is repeated RL training with better
state factors, drawdown-aware reward, and an inspectable stability report.

## External Reference Takeaways

- TradingAgents separates analysis, trading, risk review, and portfolio
  approval. This project maps that idea to factor state construction, policy
  training, risk-aware reward, and portfolio backtest validation.
- TradingAgents keeps decision logs and checkpoint/recovery concepts. This
  project should keep per-run seed/episode records and output stable artifacts.
- Vibe-Trading describes a research workflow of planning, grounding, executing,
  validating, and keeping artifacts inspectable. This project should keep JSON
  plus HTML reports that can be inspected without rerunning training.
- Vibe-Trading emphasizes benchmark comparison, walk-forward validation, and
  warnings. This project should compare RL against existing baselines and show
  mean/std/win-rate rather than one lucky run.

## Scope

This design covers:

- Root `training/` folder for user-facing training experiments.
- Multi-seed Q-learning repeated training.
- Episode sweep for 25, 50, 100, and 200 episodes by default.
- Drawdown-aware Q-learning reward.
- Additional trend factors plus RSI/MACD state inputs.
- Stability report in JSON and HTML preview form.

This design does not cover:

- Supervised learning.
- DQN/PPO.
- Manual signal overrides.
- Dashboard app.

## Factor Changes

Add trend features to the daily feature frame:

- `return_20d`
- `return_60d`
- `ma_20_slope`
- `ma_60_slope`

Q-learning state remains discrete and uses:

- `rsi_14`
- `macd_hist`
- `return_20d`
- `close_to_ma_20`
- `ma_20_slope`
- `volatility_20`
- position flag

## Reward Changes

The training reward becomes:

```text
position_exposure * next_return
- trade_penalty
- drawdown_penalty * current_drawdown
```

Drawdown is tracked inside each training episode using a lightweight equity
curve. This teaches the learner to avoid paths that earn return with excessive
peak-to-trough damage.

## Stability Report

`training/run_rl_stability_report.py` writes:

- `outputs/rl_stability_report.json`
- `outputs/rl_stability_report.html`

The report groups results by episode count and seed:

- per run: seed, episodes, total return, Sharpe, max drawdown, trade count,
  excess return versus buy-and-hold
- per episode count: mean return, std return, mean Sharpe, mean max drawdown,
  mean trade count, win rate versus buy-and-hold
- warnings for excessive trade count or unstable return dispersion

