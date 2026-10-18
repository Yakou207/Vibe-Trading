# CSI 300 cross-sectional factor lab (2026-10-19)

A read-only research track. It does not change the counted strategy, the frozen policy, the paper account or any evidence file.

## Summary

- In training, the strongest effects are low risk and low liquidity: 60-day volatility (ICIR -0.44),
  20-day turnover (-0.43), 20-day volatility, MAX and traded amount all have negative Rank IC, so calmer,
  less traded stocks did better after size and industry neutralization. Value (BP, EP) is the strongest
  positive group. Momentum is weak; only 12-month momentum clears t = 2.
- In the hold-out, EP (t 3.07) and the volatility/MAX group (t -1.9 to -2.7) keep their sign. BP fades
  to almost zero, 12-month momentum falls to zero, and ROE flips from negative to positive (t 2.71). 18 of
  27 factors keep their training sign. That is better than chance, but most hold-out t-stats are below 2.
- The prescribed equal-weight rule only keeps factors with positive training ICIR, so it drops the
  strongest negative-signed factors. Its hold-out Rank IC is close to zero (0.004).
- The ridge can put negative weight on a factor, and its hold-out Rank IC is 0.032 (t 2.59). Its Pearson
  IC is about zero, though, and its gross Q5-Q1 is -6.2% a year. Removing the 2024-09-15..10-31 rally
  turns Q5-Q1 to +5.3%: high-volatility names in its bottom quintile rallied hard in that window.
- Conclusion: there is modest, risk-shaped cross-sectional signal in this universe, and it is fragile
  to one market episode. A sign-aligned combination would be a new, predeclared test. It should run with
  costs, through the backtest runner after the same-day look-ahead fix, before anything reaches the counted strategy.

## Setup

- Panel: 2021-06-15 to 2026-10-16, 1294 sessions, point-in-time CSI 300 membership (388,200 member-days).
- Training/selection: signals through 2024-06-30, purged so the T+1+h exit open is on or before that date (732 signal dates at h=5).
- Locked hold-out: 2024-07-01 to the last date (556 signal dates). Nothing was tuned on it.
- Forward return: the signal at the T close earns hfq `open[T+1+h] / open[T+1] - 1`. Suspended entry or exit days are dropped; limit-up entries are not filtered.
- Preprocessing per date: median +/- 3 x 1.4826 x MAD, z-score, OLS residual on Shenwan level-1 dummies + z-scored log total market cap, z-score again.
- Missing inputs: 2,050 member-days lack a market cap (600705.SH, 600837.SH, 601989.SH have Baidu-only valuations) and 9,248 lack an industry; those cells are excluded, not imputed.
- Primary horizon h=5 sessions. All Rank IC t-stats divide the overlapping series by sqrt(h) (`t = ICIR * sqrt(n / h)`).

## Multiple testing

27 factors x 3 horizons = 81 tests. By chance about 3.7 would show |t| > 2; in training 34 did. The Bonferroni 5% threshold is |t| > 3.42; 21 passed it in training. 18 of 27 factors kept the sign of their h=5 Rank IC in the hold-out.

## Factors (h=5, neutralized)

| Factor | Category | Train Rank IC | Train ICIR | Train t | Hold-out Rank IC | Hold-out ICIR | Hold-out t | Hold-out Q5-Q1 ann. | Monotonicity | AC(1) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `bp` | value | 0.0413 | 0.32 | 3.92 | 0.0112 | 0.10 | 1.06 | -3.41% | -0.60 | 1.00 |
| `ep` | value | 0.0301 | 0.29 | 3.52 | 0.0346 | 0.29 | 3.07 | 9.80% | 0.90 | 1.00 |
| `mom_12m_skip1m` | momentum | 0.0310 | 0.23 | 2.29 | -0.0013 | -0.01 | -0.09 | -6.65% | -0.10 | 0.99 |
| `high_52w` | technical | 0.0254 | 0.15 | 1.59 | -0.0075 | -0.06 | -0.59 | -6.81% | -0.20 | 0.99 |
| `dist_ma250` | technical | 0.0212 | 0.14 | 1.33 | -0.0220 | -0.16 | -1.69 | -9.21% | -0.70 | 0.99 |
| `amihud_20d` | liquidity | 0.0087 | 0.12 | 1.43 | -0.0031 | -0.04 | -0.40 | -8.21% | -0.50 | 0.99 |
| `rev_20d` | reversal | 0.0120 | 0.11 | 1.28 | 0.0204 | 0.16 | 1.69 | -0.73% | -0.10 | 0.93 |
| `mom_6m_skip1m` | momentum | 0.0088 | 0.07 | 0.78 | -0.0185 | -0.14 | -1.47 | -13.18% | -0.70 | 0.98 |
| `volume_ratio_5_60` | liquidity | 0.0022 | 0.03 | 0.37 | -0.0112 | -0.13 | -1.39 | 0.80% | 0.10 | 0.93 |
| `rev_5d` | reversal | 0.0025 | 0.03 | 0.31 | 0.0191 | 0.17 | 1.74 | 4.18% | 0.70 | 0.75 |
| `cmf` | technical | 0.0005 | 0.01 | 0.07 | -0.0088 | -0.09 | -0.91 | -7.74% | -0.50 | 0.94 |
| `mom_3m_skip1m` | momentum | -0.0014 | -0.01 | -0.14 | -0.0150 | -0.12 | -1.21 | -7.84% | -0.40 | 0.97 |
| `pv_flow_signal` | technical | -0.0058 | -0.06 | -0.72 | -0.0113 | -0.11 | -1.14 | -2.52% | -0.30 | 0.93 |
| `macd_hist_norm` | technical | -0.0057 | -0.06 | -0.75 | -0.0085 | -0.07 | -0.71 | 3.24% | 0.50 | 0.96 |
| `mom_1m_skip1m` | momentum | -0.0075 | -0.07 | -0.83 | -0.0124 | -0.11 | -1.15 | -12.36% | -0.70 | 0.94 |
| `rsi14` | technical | -0.0085 | -0.08 | -0.95 | -0.0080 | -0.07 | -0.71 | 3.08% | 0.60 | 0.91 |
| `growth` | quality | -0.0096 | -0.08 | -0.97 | 0.0144 | 0.15 | 1.61 | 14.78% | 0.70 | 0.99 |
| `obv_momentum` | technical | -0.0083 | -0.09 | -1.11 | -0.0108 | -0.12 | -1.21 | 2.99% | 0.20 | 0.94 |
| `dist_ma20` | technical | -0.0114 | -0.10 | -1.23 | -0.0169 | -0.13 | -1.41 | 3.83% | 0.30 | 0.90 |
| `abnormal_turnover` | liquidity | -0.0071 | -0.10 | -1.19 | -0.0103 | -0.12 | -1.25 | 0.00% | 0.10 | 0.99 |
| `dist_ma60` | technical | -0.0143 | -0.11 | -1.25 | -0.0233 | -0.17 | -1.79 | -0.69% | -0.40 | 0.97 |
| `roe` | quality | -0.0136 | -0.18 | -2.08 | 0.0248 | 0.26 | 2.71 | 13.56% | 0.90 | 1.00 |
| `log_amount_20d` | liquidity | -0.0350 | -0.32 | -3.84 | -0.0109 | -0.08 | -0.86 | 4.97% | 0.60 | 1.00 |
| `max_ret_20d` | volatility | -0.0350 | -0.38 | -4.52 | -0.0273 | -0.26 | -2.68 | -5.74% | -0.20 | 0.95 |
| `vol_20d` | volatility | -0.0429 | -0.39 | -4.63 | -0.0245 | -0.19 | -1.94 | 4.76% | 0.50 | 0.98 |
| `turnover_20d` | liquidity | -0.0418 | -0.43 | -5.11 | -0.0165 | -0.13 | -1.37 | 7.78% | 0.30 | 1.00 |
| `vol_60d` | volatility | -0.0535 | -0.44 | -5.20 | -0.0289 | -0.20 | -2.08 | 0.69% | 0.10 | 1.00 |

Q5-Q1 uses equal-weight quintiles rebalanced every h sessions on non-overlapping periods, before costs. Train Rank IC for h=1 and h=20, IC decay, Pearson IC, quintile turnover and the full correlation matrix are in the JSON.

## IC decay (training, mean Rank IC vs the one-day return k sessions ahead)

| Factor | k=1 | k=2 | k=3 | k=5 | k=10 | k=20 |
|---|---:|---:|---:|---:|---:|---:|
| `bp` | 0.0273 | 0.0266 | 0.0264 | 0.0261 | 0.0263 | 0.0264 |
| `ep` | 0.0175 | 0.0167 | 0.0168 | 0.0167 | 0.0172 | 0.0176 |
| `mom_12m_skip1m` | 0.0226 | 0.0233 | 0.0232 | 0.0227 | 0.0217 | 0.0221 |
| `high_52w` | 0.0221 | 0.0232 | 0.0246 | 0.0252 | 0.0257 | 0.0310 |
| `dist_ma250` | 0.0161 | 0.0172 | 0.0183 | 0.0191 | 0.0206 | 0.0255 |
| `amihud_20d` | 0.0068 | 0.0064 | 0.0065 | 0.0074 | 0.0071 | 0.0066 |
| `rev_20d` | 0.0085 | 0.0069 | 0.0055 | 0.0037 | 0.0011 | -0.0001 |
| `mom_6m_skip1m` | 0.0118 | 0.0123 | 0.0132 | 0.0130 | 0.0138 | 0.0172 |

## Highly correlated pairs (training, |mean Spearman| > 0.7)

- `pv_flow_signal` / `obv_momentum`: 0.93
- `dist_ma250` / `high_52w`: 0.85
- `rsi14` / `dist_ma20`: 0.85
- `rev_20d` / `dist_ma20`: -0.82
- `vol_20d` / `max_ret_20d`: 0.82
- `vol_20d` / `vol_60d`: 0.81
- `macd_hist_norm` / `dist_ma20`: 0.78
- `pv_flow_signal` / `cmf`: 0.78
- `rev_20d` / `dist_ma60`: -0.78
- `log_amount_20d` / `amihud_20d`: -0.75
- `rev_20d` / `pv_flow_signal`: -0.74
- `mom_6m_skip1m` / `dist_ma250`: 0.74
- `rev_20d` / `rsi14`: -0.73
- `turnover_20d` / `log_amount_20d`: 0.72
- `mom_12m_skip1m` / `dist_ma250`: 0.72
- `dist_ma20` / `dist_ma60`: 0.70
- `rev_5d` / `dist_ma20`: -0.70

## Combined signals (hold-out)

| Signal | Hold-out Rank IC h=1 | h=5 | h=20 | Hold-out ICIR h=5 | Hold-out t h=5 | Pearson IC h=5 | Q5-Q1 ann. h=5 | Q5-Q1 Sharpe h=5 | Top-quintile turnover h=5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| equal_weight | 0.0057 | 0.0040 | -0.0055 | 0.03 | 0.36 | 0.0065 | -4.70% | -0.30 | 25.45% |
| ridge | 0.0221 | 0.0324 | 0.0393 | 0.25 | 2.59 | -0.0021 | -6.24% | -0.33 | 18.05% |
| equal_weight, ex 2024-09-15..2024-10-31 | 0.0080 | 0.0095 | 0.0048 | 0.09 | 0.88 | 0.0133 | 6.84% | 0.54 | 25.92% |
| ridge, ex 2024-09-15..2024-10-31 | 0.0225 | 0.0361 | 0.0463 | 0.28 | 2.89 | 0.0011 | 5.30% | 0.32 | 18.43% |

- Equal weight: mean of the 11 neutralized factors with positive training Rank ICIR at h=5, re-standardized per date: `mom_6m_skip1m`, `mom_12m_skip1m`, `rev_5d`, `rev_20d`, `amihud_20d`, `volume_ratio_5_60`, `ep`, `bp`, `dist_ma250`, `high_52w`, `cmf`. Its in-sample training Rank IC (h=5) is 0.0348, for reference only.
- Ridge: all 27 neutralized factors, fixed penalty 0.1 (not tuned), target = cross-sectional z-scored rank of the 5-day forward return. Expanding window, refit on 2024-07-01 (213,445 rows, last signal 2024-06-20), 2025-07-01 (284,258 rows, last signal 2025-06-20), 2026-07-01 (355,438 rows, last signal 2026-06-22); each fit uses only returns whose exit open is before its refit date.

## Reading the results

- These are gross, equal-weight, daily-data statistics on 300 large caps. They are a screen for which factors deserve a costed backtest, not evidence of tradable profit.
- Rank IC measures ordering; Pearson IC and quintile means are dominated by extreme returns. When they disagree (positive Rank IC, flat Pearson IC, negative Q5-Q1), a few large winners in the bottom quintile outweigh a correct ordering of the typical stock.
- Hold-out numbers are the only out-of-sample evidence here; training columns were used for selection and are optimistic by construction.
- Industry labels are the current CNInfo Shenwan history; a symbol whose first record is after a date takes its earliest label (minor classification look-ahead).

JSON: `/Users/yakou/Desktop/Vibe-Trading/outputs/research/factor_lab/factor_lab.json` (gitignored). Rerun: `.venv/bin/python scripts/run_factor_lab.py`.
