# Q-Learning RL v1 Design

## Purpose

Build the first learnable reinforcement-learning trading strategy for the
A-share daily research system. The version must be simple, auditable, and
comparable with the current real buy-and-hold backtest before any DQN upgrade.

## Scope

This design covers:

- Tabular Q-learning over discretized daily feature states.
- Walk-forward train/test evaluation using existing windows.
- Strict train/test separation to avoid look-ahead bias.
- Same-cost, same-risk, same-engine comparison against buy-and-hold.
- A JSON report for RL vs buy-and-hold metrics.
- Interfaces that can later be replaced by DQN without changing the report
  command contract.

This design does not cover:

- Deep Q-networks, PPO, or stable-baselines integration.
- Hyperparameter search.
- Multi-agent research workflows.
- Live or paper brokerage execution.

## Assumptions

- Input is `data/processed/akshare_research_features.csv`.
- The first RL v1 policy trains on one symbol at a time and reports aggregated
  walk-forward windows across the available symbols in the test data.
- Q-learning uses only rows inside the training window.
- State bins are fitted only from the training window, then reused unchanged on
  the test window.
- Rewards use next-day close-to-close return for the training update, including
  a small trade penalty. The final comparison uses the real portfolio backtest
  engine, not the training reward directly.
- Buy/sell/hold actions map to the existing `TradeAction` values.
- The report is research evidence, not a production trading recommendation.

## State Design

The state is a tuple of discrete values:

- RSI bin from `rsi_14`: low, mid, high.
- MACD histogram sign from `macd_hist`: negative, flat, positive.
- 5-day return bin from `return_5d`: down, neutral, up.
- 20-day volatility bin from `volatility_20`: low, mid, high.
- Position flag: flat or long.

The bin thresholds for `return_5d` and `volatility_20` are fitted from training
data only. RSI and MACD use fixed thresholds.

## Q-Learning

The learner stores a dictionary:

```text
(state, action) -> q_value
```

Training iterates over sorted train rows per symbol. For each row with a valid
next-day target return:

1. Build the current state from current-row features and current position flag.
2. Select an epsilon-greedy action.
3. Convert the action into a simple position transition.
4. Compute reward from next-day return, position exposure, and trade penalty.
5. Build the next state from the next row.
6. Update the Q-value with the standard Bellman equation.

The default hyperparameters are intentionally conservative:

- Episodes: 25.
- Alpha: 0.1.
- Gamma: 0.95.
- Epsilon-greedy exploration: starts at 0.2, decays by 0.95 per episode, and
  floors at 0.05.
- Trade penalty: 0.0005.

## Strategy Adapter

The trained Q-table becomes `QLearningStrategy`, which implements the existing
strategy interface:

```python
def decide(self, state: dict[str, object]) -> TradeDecision
```

The adapter discretizes current-row features with the fitted bin spec and
position flag. It chooses the highest-Q action. If no Q-values exist for a
state, it returns hold.

This keeps DQN migration clean: a future DQN strategy can implement the same
`decide()` interface and be evaluated by the same backtest/report command.

## Walk-Forward Evaluation

The script evaluates existing rolling windows:

1. Split features with `rolling_windows(..., train_years=2, test_years=1)`.
2. For each window, train the Q-table only on `train`.
3. Backtest `QLearningStrategy` only on `test`.
4. Backtest `EqualWeightBuyAndHoldStrategy` on the same `test`.
5. Save both metrics and RL excess return for the window.

This prevents look-ahead bias because no bin fitting, Q updates, or policy
selection uses test-window rows before the test backtest.

## Report

`scripts/run_walk_forward_q_learning.py` writes
`outputs/rl_vs_buy_hold_report.json` with:

- Strategy name.
- Hyperparameters.
- Feature/state configuration.
- Per-window train/test date ranges.
- RL metrics.
- Buy-and-hold metrics.
- Excess return.
- Q-state count.
- Trade counts.

## Testing

Tests must prove:

- State bins are fitted from train data and can transform test data.
- Q-learning updates a Q-value for a simple profitable action sequence.
- `QLearningStrategy` returns buy/sell/hold through the existing strategy
  interface.
- Walk-forward report code trains on train rows and evaluates on test rows.
- The CLI writes `outputs/rl_vs_buy_hold_report.json`.
- Existing tests still pass.
