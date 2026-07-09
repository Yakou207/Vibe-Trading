# Real-Data Benchmark Evaluation Design

## Goal

Run the current `main` research chain on the existing 30 STAR Market stocks and make every strategy comparison judge performance against CSI 300 and SSE Composite benchmarks, without changing strategy logic before a real baseline exists.

## Assumptions

- The baseline window is `2021-06-16` through `2026-06-16`, matching the local AkShare raw daily data span.
- The selected universe is `data/processed/akshare_research_universe.csv`.
- Existing processed files may contain fixtures, so real-run outputs must use run-specific filenames or directories.
- Strategy logic remains unchanged for this pass. This produces evidence, not optimized behavior.
- The useful q-learning branch item is the resumable DQN checkpoint capability only. Q-learning must not become an active strategy path again.

## Approach

Use the current daily pipeline to rebuild daily bars, features, market state, RL state samples, scoring coverage, stock analysis, and baseline reports into a dated real-data output namespace. Then run the current DQN walk-forward script against that RL state dataset. This keeps raw AkShare files untouched and makes generated artifacts reproducible by path.

Extend the strategy comparison layer so it can load benchmark index CSVs from `scripts/fetch_market_state.py`, normalize `index_close` into a net-value curve, align benchmark dates to the strategy equity dates, and report benchmark-relative performance. The comparison output should retain existing baseline-versus-candidate fields and add explicit benchmark-relative fields.

Port DQN checkpoint/resume support into the current DQN implementation in the smallest compatible way. If the old checkpoint code assumes an obsolete DQN API, adapt only the serialization concept and tests to the current `torch_dqn.py` / walk-forward path.

## Data Flow

1. Fetch or reuse index state for `sh000001` and CSI 300 over the real-data window.
2. Run `scripts/run_daily_research_pipeline.py` with the 30-stock universe and run-specific outputs.
3. Run `scripts/run_dqn_walk_forward.py` using the generated RL state dataset.
4. Run `scripts/compare_strategy_reports.py` with baseline, candidate, and benchmark CSV inputs.
5. Summarize generated report paths and key metrics.

## Benchmark Metrics

For each strategy versus each benchmark:

- `excess_return`: strategy total return minus benchmark total return over aligned dates.
- `tracking_max_drawdown`: maximum drawdown of the strategy net-value divided by benchmark net-value.
- Walk-forward segment benchmark returns and segment excess returns.

## Non-Goals

- No live brokerage integration.
- No high-frequency data.
- No strategy reward redesign in this pass.
- No expansion beyond the existing 30-stock universe.
- No direct merge of the old q-learning branch.

## Verification

- Add failing tests for benchmark loading, date alignment, excess return, and tracking max drawdown.
- Add failing tests for DQN checkpoint save/load or resumable training on the current DQN path.
- Run targeted tests until green.
- Run the real-data pipeline and DQN walk-forward commands.
- Inspect output row counts and report metrics before calling the run complete.
