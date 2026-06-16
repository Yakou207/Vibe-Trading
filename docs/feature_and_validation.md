# Feature Engineering and Walk-Forward Validation

## Current Scope

- Input: `data/processed/akshare_research_daily.csv`
- Output: `data/processed/akshare_research_features.csv`
- Frequency: daily
- Universe: 30 STAR Market stocks
- Action labels: `buy`, `sell`, `hold`
- Baseline strategy: buy and hold

## Feature Set

The current feature table contains 30 model input columns:

- Raw market fields: open, high, low, close, volume, after-hours volume and
  amount, outstanding shares, turnover.
- Return features: 1-day return, 5-day return, 1-day log return.
- Trend features: 5/10/20/60-day moving averages and close-to-moving-average
  ratios.
- Volume features: 5/20-day volume averages and 20-day volume ratio.
- Risk/shape features: 20-day volatility, high-low range, close position within
  the daily range.
- Momentum indicators: RSI-14, MACD, MACD signal, MACD histogram.

## Look-Ahead Bias Controls

- Indicator features are computed per symbol using current and historical rows
  only.
- `target_next_return_1d` and `target_action` are labels, not model input
  features.
- Walk-forward validation slices train and test windows by date before baseline
  evaluation.
- Test metrics use only out-of-sample rows inside each test window.

## Validation Modes

- Rolling window: 2 years in-sample training, followed by 1 year out-of-sample
  testing. The whole window then rolls forward one year.
- Expanding window: initial 2 years in-sample training, followed by 1 year
  out-of-sample testing. The train window then expands while the test window
  rolls forward one year.

## Current Baseline Output

Run:

```bash
PYTHONPATH=src python scripts/run_walk_forward_baseline.py
```

Output:

- `outputs/walk_forward_buy_hold.json`

The baseline does not train a predictive model yet. It uses the walk-forward
splits to establish an auditable evaluation scaffold before adding learned
strategies.
