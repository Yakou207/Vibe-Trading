# Pre-Market Dashboard & `/picks` Context Data Contract

This document defines the JSON data contract consumed by **two surfaces**:

1. **`GET /api/premarket-context`** (served by `scripts/serve_trading_desk.py` and embedded in static `picks.html`) — powers the collapsible Pre-Market Pulse & Pitfall Radar panel, inline pool badges (TOP 5 & Shadow Pool v2), and active stock-card auction/pitfall callouts directly inside **`/picks`** (maintaining the clean 2-page `交易桌 /` + `选股 /picks` architecture).
2. **Standalone Paper-Trade Brief CLI (`scripts/build_premarket_brief.py`)** — writes `outputs/premarket/<date>/brief.json`, `auction.json`, `brief.html`, and `brief_auction.html` using `src/fintech_quant/reports/premarket_template.html`.

All new fields introduced in PR #2 are **strictly optional** and **100% backwards-compatible** with existing `brief.json` and `auction.json` files (`schema_version = 1`). When an optional block is omitted or no pre-market file exists yet, `/api/premarket-context` returns a graceful unavailable payload and `/picks` renders a quiet single-line placeholder instead of erroring.

> **Evidence boundary**: Nothing in `/api/premarket-context`, `brief.json`, or `auction.json` ever mutates `data/paper/` or `outputs/paper_trading/.../cycles/`, and nothing here counts toward V2 paper-trading evidence (`counts_toward_paper_evidence: false`).

---

## `/api/premarket-context` Endpoint Response

`scripts/serve_trading_desk.py` reads the latest `outputs/premarket/<date>/brief.json` (plus sibling `auction.json`, if present) under `--premarket-root` and projects it into a compact payload for `/picks`:

```json
{
  "status": "ok",
  "signal_date": "2026-11-05",
  "market_pulse": { "...": "see section 1 below" },
  "pitfall_calendar": { "status": "ok", "alerts": [] },
  "auction": {
    "signal_date": "2026-11-05",
    "benchmark_gap_pct": 0.0042,
    "near_limit_pct": 0.01,
    "large_gap_pct": 0.05,
    "by_symbol": {
      "999001.SH": {
        "symbol": "999001.SH",
        "category": "target",
        "auction_price": 345.12,
        "gap_pct": 0.012,
        "auction_volume_ratio": 0.1619,
        "relative_gap_pct": 0.0078,
        "stop_distance_at_auction_pct": 0.0593,
        "flags": ["auction_volume_surge"]
      }
    }
  }
}
```

When no brief exists yet (or neither `market_pulse`, `pitfall_calendar`, nor `auction.json` is populated), `/api/premarket-context` returns:

```json
{
  "status": "unavailable",
  "signal_date": null,
  "market_pulse": { "status": "unavailable" },
  "pitfall_calendar": { "status": "not_checked", "alerts": [] },
  "auction": null
}
```

---

## Conventions

- **Percentages (`*_pct`)**: Always expressed as **decimal ratios** (e.g. `0.0125` = `+1.25%`, `-0.008` = `-0.80%`, `0.67` = `67.0%`, `0.08` = `8.0%`). This matches `gap_pct`, `near_limit_pct`, `large_gap_pct` in `premarket_brief.py` and `drawdown_reduce` / `paper_return` in `desk.py`.
- **Turnover (`turnover_cny_bn`)**: Expressed in **billion CNY (十亿元)**. For example, `1465.8` renders as `¥1.47万亿` (`1465.8B`), and `845.2` renders as `¥8452亿`.
- **Dates**: ISO-8601 `YYYY-MM-DD` (Asia/Shanghai trading calendar).
- **A-share color semantics**: Positive moves (`>= 0`) render in `--up` (red); negative moves (`< 0`) render in `--down` (green).

---

## Top-Level `brief.json` Extensions

Existing fields (`schema_version`, `kind`, `signal_date`, `execution`, `capital`, `near_miss_floor`, `policy`, `counts_toward_paper_evidence`, `live_trading_enabled`, `sources`, `scoring_v2`, `systemic_risk`, `targets`, `near_miss`, `paper_exits`) remain unchanged.

### 1. `market_pulse` (optional)

Top-of-page macro, headline index, breadth, and overnight overseas strip.

```json
{
  "market_pulse": {
    "status": "ok",
    "regime": "risk_on",
    "regime_note": "主要宽基站上 20/50 日均线，量能温和放大",
    "indices": [
      {
        "symbol": "000001.SH",
        "name": "上证指数",
        "close": 3386.42,
        "change_pct": 0.0068,
        "sparkline": [3290.1, 3304.5, 3318.2, 3386.42],
        "above_ma20": true,
        "above_ma50": true,
        "above_ma250": true
      }
    ],
    "breadth": {
      "advancers": 3180,
      "decliners": 1790,
      "unchanged": 172,
      "limit_up_count": 64,
      "limit_down_count": 6,
      "turnover_cny_bn": 1465.8,
      "turnover_vs_5d_pct": 0.118,
      "csi300_above_ma20_pct": 0.67,
      "csi300_above_ma50_pct": 0.58,
      "csi300_above_ma250_pct": 0.63
    },
    "overseas": [
      { "symbol": "FTSE.A50", "name": "富时A50", "value": 13482.5, "change_pct": 0.0042 },
      { "symbol": "NDX", "name": "纳斯达克", "value": 19120.4, "change_pct": 0.0068 },
      { "symbol": "SPX", "name": "标普500", "value": 5942.1, "change_pct": 0.0045 },
      { "symbol": "HXC", "name": "纳斯达克金龙", "value": 7128.0, "change_pct": 0.0115 },
      { "symbol": "USDCNH", "name": "离岸人民币", "value": 7.184, "change_pct": -0.0014 }
    ],
    "sector_alerts": [
      {
        "industry": "电力设备",
        "peer": "海外光伏与储能指数",
        "change_pct": 0.021,
        "note": "隔夜海外新能源板块走强，观察早盘竞价承接"
      }
    ]
  }
}
```

| Field | Type | Values / Notes |
|---|---|---|
| `status` | `string` | `"ok" \| "partial" \| "unavailable"` |
| `regime` | `string` | `"risk_on" \| "neutral" \| "risk_off" \| "unknown"` |
| `regime_note` | `string` | Short 1-line summary shown in the Market Pulse header |
| `live_status` | `string` (optional) | `"intraday_live" \| "today_close_live" \| "post_close"` — in-memory live overlay freshness indicator |
| `live_date` | `string \| null` (optional) | Live trading date (`YYYY-MM-DD`) when overlaid ahead of today's post-close brief |
| `live_as_of` | `string \| null` (optional) | Live quote timestamp (`HH:MM`, `Asia/Shanghai`) when `live_status` is `"intraday_live"` or `"today_close_live"` |
| `indices` | `array` | Recommended 6 headline A-share indices: `000001.SH` 上证指数, `399001.SZ` 深证成指, `399006.SZ` 创业板指, `000300.SH` 沪深300, `000905.SH` 中证500, `000688.SH` 科创50 |
| `indices[].sparkline` | `list[float]` | Recent closes (typically 20 trading days), rendered as inline SVG; live overlay appends today's live price when `live_date > signal_date` |
| `indices[].above_ma20/50/250` | `bool \| null` | Rendered as 3 MA regime dots (`20`, `50`, `250`); recomputed live when `ma20/50/250` reference levels are present |
| `indices[].ma20/50/250` | `float \| null` (optional) | Numeric MA reference levels stored by `premarket_data.py` so live overlay can update `above_ma*` accurately |
| `breadth` | `object \| null` | Market advancers/decliners/unchanged, limit-up/down counts, total turnover, vs-5d ratio, CSI 300 MA breadth percentages |
| `overseas` | `array` | Overnight global / A50 / FX reference pills |
| `sector_alerts` | `array` (optional) | Industry-linked overseas peer moves |

---

### 2. `pitfall_calendar` (optional)

Quiet-by-default pre-market pitfall radar covering corporate actions, share unlocks, earnings windows, suspensions, and negative overnight notices.

```json
{
  "pitfall_calendar": {
    "status": "ok",
    "alerts": [
      {
        "symbol": "999003.SH",
        "name": "明川汽车",
        "kind": "earnings",
        "severity": "medium",
        "date": "2026-11-06",
        "title": "业绩说明会窗口",
        "detail": "拟于次一交易日盘后召开三季报业绩说明会，留意盘中波动扩大。"
      }
    ]
  }
}
```

| Field | Type | Values / Notes |
|---|---|---|
| `status` | `string` | `"ok" \| "not_checked" \| "partial"` |
| `alerts` | `array` | Empty array with `status: "ok"` renders a calm single-line green pass banner |
| `alerts[].kind` | `string` | `"ex_dividend" \| "unlock" \| "earnings" \| "overnight_negative" \| "suspension"` |
| `alerts[].severity` | `string` | `"high" \| "medium" \| "info"` |
| `alerts[].date` | `string` | Event date (`YYYY-MM-DD`) |
| `alerts[].title` | `string` | Short headline |
| `alerts[].detail` | `string` | Concise 1-2 sentence explanation |

---

### 3. `portfolio_summary` (computed automatically in `build_brief`)

Automatically derived in `build_brief()` from `paper_report.json`, `targets.csv`, `policy`, and `capital`. No external fetcher is needed.

```json
{
  "portfolio_summary": {
    "paper_equity": 101071.43,
    "paper_cash": 79121.43,
    "actual_peak": 101071.43,
    "drawdown_pct": 0.0,
    "drawdown_reduce_limit": 0.08,
    "drawdown_liquidate_limit": 0.09,
    "buffer_to_reduce_pct": 0.08,
    "buffer_to_liquidate_pct": 0.09,
    "planned_buy_notional": 19540.0,
    "projected_exposure_pct": 0.1954
  }
}
```

| Field | Type | Notes |
|---|---|---|
| `paper_equity` | `float \| null` | `paper_report.nav.equity` |
| `paper_cash` | `float \| null` | `paper_report.account.cash` |
| `actual_peak` | `float \| null` | `account.drawdown_control_state.actual_peak` (fallback: `paper_equity`) |
| `drawdown_pct` | `float \| null` | `max(0.0, 1 - paper_equity / actual_peak)` |
| `drawdown_reduce_limit` | `float` | `policy.drawdown_reduce` (default `0.08`) |
| `drawdown_liquidate_limit` | `float` | `policy.drawdown_liquidate` (default `0.09`) |
| `buffer_to_reduce_pct` | `float \| null` | `drawdown_reduce_limit - drawdown_pct` |
| `buffer_to_liquidate_pct` | `float \| null` | `drawdown_liquidate_limit - drawdown_pct` |
| `planned_buy_notional` | `float` | Sum of `suggested.notional` across `targets` |
| `projected_exposure_pct` | `float` | `planned_buy_notional / capital` |

---

### 4. Optional Row-Level Enrichments (`targets[]`, `near_miss[]`, `paper_exits[]`)

#### `luk_setup` (optional)

Attach Martin Luk setup diagnostics (from `fintech_quant.research.momentum_setup.screen`) to any brief row:

```json
{
  "luk_setup": {
    "state": "trigger",
    "stop_price": 176.2,
    "stop_pct": 0.048,
    "confluence": 3,
    "reward_r": 2.6,
    "base_days": 28,
    "trigger_note": "EMA9/21 多头排列，放量收复平台中枢"
  }
}
```

- `state`: `"trigger" | "setup" | "leader_weak_base" | "leader_no_base" | "avoid"`
- `stop_price`: float (also used by `evaluate_auction` to compute `stop_distance_at_auction_pct`)
- `stop_pct`: decimal ratio (e.g. `0.048` = `4.8%`)

#### `overnight_announcements` (enriched existing field)

```json
{
  "overnight_announcements": {
    "status": "ok",
    "items": [
      {
        "title": "曜辰新能发布 2026 年三季报",
        "published_at": "2026-11-05 18:10",
        "source": "cninfo_notice",
        "polarity": "positive",
        "url": "",
        "summary": "前三季度营收同比增长 14.6%，现金流保持平稳。"
      }
    ]
  }
}
```

- `status`: `"not_checked" | "ok" | "clear" | "alert"`
- `items[].polarity`: `"positive" | "neutral" | "negative"` (optional)

---

## `evaluate_auction` Optional Enrichments (`auction.json`)

`evaluate_auction(brief, quotes, near_limit_pct=0.01, large_gap_pct=0.05, *, benchmark_gap_pct=None)` remains 100% backwards-compatible. When optional inputs are omitted, output keys and flags are identical to v1.

### Optional Inputs

1. **Per-quote turnover fields** (or `item["avg_turnover_20d"]`):
   - `quote["auction_turnover"]`: 09:25 call auction turnover (CNY)
   - `quote["avg_turnover_20d"]`: 20-day average daily turnover (CNY)
   - Computes `check["auction_volume_ratio"] = round(auction_turnover / avg_turnover_20d, 4)`.
   - Flags:
     - `auction_volume_surge` when `auction_volume_ratio >= 0.15`
     - `auction_thin_liquidity` when `auction_volume_ratio < 0.005`
2. **`benchmark_gap_pct`** keyword argument (e.g. CSI 300 09:25 auction gap as decimal ratio):
   - Stored on top-level `auction["benchmark_gap_pct"]`
   - Computes `check["relative_gap_pct"] = round(gap_pct - benchmark_gap_pct, 6)`
   - Flags:
     - `weak_vs_index` when `relative_gap_pct <= -0.02`
     - `strong_vs_index` when `relative_gap_pct >= 0.03`
3. **Row-level `item["luk_setup"]["stop_price"]`**:
   - Computes `check["stop_distance_at_auction_pct"] = round((auction_price - stop_price) / auction_price, 6)`
   - Flags:
     - `below_luk_stop` when `auction_price <= stop_price`
     - `stop_too_wide` when `stop_distance_at_auction_pct > 0.08`

---

## Real Data Sources

Real mode is wired up. `docs/operations.md` (盘前选股简报 section) describes the schedule and the
cache rules.

| Block | Built by | Sources |
|---|---|---|
| `market_pulse.indices`, `breadth` | `information/premarket_data.py`, run by the post-close job (`build_premarket_brief.py --market-data`) | Sina index daily bars; Legu market activity; Tencent SSE/SZSE composite turnover; local hfq signal prices |
| `pitfall_calendar` (ex-dividend, unlock, suspension, earnings) | same | pipeline raw corporate actions (local); Eastmoney unlock, suspension, report schedule |
| `market_pulse.overseas` | `information/premarket_live.py`, fetched on demand by the desk | Sina quotes (A50, Nasdaq, S&P 500, Golden Dragon, USD/CNH) |
| `market_pulse` (live A-share overlay) | same (in-memory only; never mutates `brief.json`) | Single Tencent batch for 6 headline indices + SSE/SZSE turnover, plus Legu full-market breadth (weekdays `09:25–15:05` 60s TTL as `intraday_live`; `15:05+` 600s TTL as `today_close_live` until today's post-close brief lands) |
| `pitfall_calendar` (`overnight_negative`) | same | Eastmoney per-stock notices, tagged with `event_nlp` |
| `auction` | same | Tencent quotes; `luk_setup` from the picker screen; 20-day turnover from local execution prices |

`/api/premarket-context` additionally returns `notices_pending` (`bool`) and a `live` object
(`segment`, `refreshing`, `overseas_fetched_at`, `notices_fetched_at`, `notices_status`,
`notices_checked`, `notices_pending`, `brief`), and `auction` carries `mode` (`auction` |
`open_fallback`) and `captured_at`.

### Fast / Slow Channel Query Parameters

- `GET /api/premarket-context` (default, no `phase`): backwards-compatible combined payload.
- `GET /api/premarket-context?phase=fast`: runs only fast parallel fetches (live A-share 6 indices
  + turnover + Legu breadth + overseas + auction check) and skips the slow up-to-60-stock overnight
  notice scan, returning `notices_pending: true` when notices still need to be scanned in phase 2.
- `GET /api/premarket-context?phase=notices`: runs the overnight notice scan and returns
  `{status, signal_date, pitfall_calendar, notices_updated_at, notices_pending: false, live}`.
- `?refresh=1` bypasses live TTL caches (on `?phase=fast&refresh=1`, clears live pulse, overseas,
  and notices so phase 2 fetches fresh notices too). In `--demo` mode and static GitHub Pages
  exports, all `phase` values stay 100% offline with `notices_pending: false`.
