"""Daily-bar adaptation of Martin Luk's "buy weakness inside strength" setup.

Four steps, each a deterministic check on adjusted (hfq) daily bars:

1. Leader: 1/3/6-month returns rank in the top 30% of the universe. Luk's absolute 30% hurdles
   are recorded but not required, because CSI 300 large caps rarely clear them.
2. Base: the last eight weeks (40 sessions) stay inside a 25% range.
3. Strength in the base: higher lows, a rising 21 EMA and a close above it; a close under a falling
   9 or 21 EMA, or lower highs with lower lows, means avoid.
4. Confluence trigger: at least two supports (9/21/50 EMA, AVWAPs anchored at the six-month swing
   low/high, a prior pivot, an unfilled gap) sit within 1.5% of each other near the price. The day
   "flushes" into that zone (low touches it) and reclaims it (closes above it, up on the day).
   The stop is the day's low and must be within 4%.

Without intraday data the flush and reclaim are read from one daily bar. A-share T+1 means the
stop cannot be honoured on the entry day. This is research tooling, not a trading signal service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence


@dataclass(frozen=True)
class Bar:
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    suspended: bool = False


@dataclass(frozen=True)
class SetupConfig:
    momentum_windows: tuple[int, int, int] = (21, 63, 126)
    leader_percentile: float = 0.70
    absolute_momentum: float = 0.30
    base_sessions: int = 40
    max_base_depth: float = 0.25
    swing_lookback: int = 126
    gap_lookback: int = 60
    support_window_below: float = 0.05
    support_window_above: float = 0.01
    confluence_band: float = 0.015
    min_confluence: int = 2
    max_stop_pct: float = 0.04


STATE_ORDER = {"trigger": 0, "setup": 1, "leader_weak_base": 2, "leader_no_base": 3, "avoid": 4}


@dataclass
class SymbolSeries:
    """Precomputed indicator arrays so any session can be analysed in O(lookback)."""

    symbol: str
    bars: list[Bar]
    ema9: list[float] = field(default_factory=list)
    ema21: list[float] = field(default_factory=list)
    ema50: list[float] = field(default_factory=list)
    cum_pv: list[float] = field(default_factory=list)
    cum_v: list[float] = field(default_factory=list)
    index_by_date: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        closes = [bar.close for bar in self.bars]
        self.ema9 = ema(closes, 9)
        self.ema21 = ema(closes, 21)
        self.ema50 = ema(closes, 50)
        pv = v = 0.0
        for bar in self.bars:
            pv += (bar.high + bar.low + bar.close) / 3.0 * bar.volume
            v += bar.volume
            self.cum_pv.append(pv)
            self.cum_v.append(v)
        self.index_by_date = {bar.trade_date: i for i, bar in enumerate(self.bars)}

    def avwap(self, anchor: int, end: int) -> float | None:
        before_pv = self.cum_pv[anchor - 1] if anchor > 0 else 0.0
        before_v = self.cum_v[anchor - 1] if anchor > 0 else 0.0
        volume = self.cum_v[end] - before_v
        return None if volume <= 0 else (self.cum_pv[end] - before_pv) / volume

    def avwap_series(self, anchor: int, end: int) -> list[float | None]:
        return [self.avwap(anchor, i) for i in range(anchor, end + 1)]


def ema(values: Sequence[float], span: int) -> list[float]:
    alpha = 2.0 / (span + 1.0)
    result: list[float] = []
    for value in values:
        result.append(value if not result else result[-1] + alpha * (value - result[-1]))
    return result


def momentum_table(
    series: Mapping[str, SymbolSeries], trade_date: str, config: SetupConfig = SetupConfig()
) -> dict[str, dict[str, float]]:
    """Returns and cross-sectional percentiles for symbols that traded on ``trade_date``."""
    longest = max(config.momentum_windows)
    returns: dict[str, dict[str, float]] = {}
    for symbol, item in series.items():
        i = item.index_by_date.get(trade_date)
        if i is None or i < longest or item.bars[i].suspended:
            continue
        close = item.bars[i].close
        returns[symbol] = {
            f"r{window}": close / item.bars[i - window].close - 1.0
            for window in config.momentum_windows
        }
    for key in [f"r{window}" for window in config.momentum_windows]:
        ordered = sorted(returns, key=lambda symbol: returns[symbol][key])
        denominator = max(1, len(ordered) - 1)
        for rank, symbol in enumerate(ordered):
            returns[symbol][f"{key}_pct"] = rank / denominator
    for row in returns.values():
        row["momentum_pct"] = sum(row[f"r{w}_pct"] for w in config.momentum_windows) / len(
            config.momentum_windows
        )
    return returns


def analyze_at(
    item: SymbolSeries,
    trade_date: str,
    momentum: Mapping[str, float] | None,
    config: SetupConfig = SetupConfig(),
) -> dict[str, object]:
    i = item.index_by_date.get(trade_date)
    if i is None or item.bars[i].suspended:
        return {"symbol": item.symbol, "trade_date": trade_date, "state": "no_bar", "checks": []}
    if momentum is None or i < max(config.momentum_windows):
        return {
            "symbol": item.symbol,
            "trade_date": trade_date,
            "state": "insufficient_history",
            "checks": [],
        }
    bars = item.bars
    bar = bars[i]
    base = bars[i - config.base_sessions + 1 : i + 1]
    base_high = max(b.high for b in base)
    base_low = min(b.low for b in base)
    base_depth = 1.0 - base_low / base_high
    half = config.base_sessions // 2
    recent, prior = bars[i - half + 1 : i + 1], bars[i - config.base_sessions + 1 : i - half + 1]
    higher_lows = min(b.low for b in recent) > min(b.low for b in prior)
    lower_highs = max(b.high for b in recent) < max(b.high for b in prior)
    lower_lows = not higher_lows
    ema9, ema21, ema50 = item.ema9[i], item.ema21[i], item.ema50[i]
    ema9_rising = ema9 > item.ema9[i - 5]
    ema21_rising = ema21 > item.ema21[i - 5]
    range10 = sum((b.high - b.low) / b.close for b in bars[i - 9 : i + 1]) / 10
    range40 = sum((b.high - b.low) / b.close for b in base) / len(base)
    contraction = range10 < range40

    leader = momentum["momentum_pct"] >= config.leader_percentile and all(
        momentum[f"r{w}"] > 0 for w in config.momentum_windows
    )
    absolute = all(momentum[f"r{w}"] >= config.absolute_momentum for w in config.momentum_windows)
    avoid_reasons = []
    if bar.close < ema9 and not ema9_rising:
        avoid_reasons.append("收盘在下行的 9 EMA 之下")
    if bar.close < ema21 and not ema21_rising:
        avoid_reasons.append("收盘在下行的 21 EMA 之下")
    if lower_highs and lower_lows:
        avoid_reasons.append("更低高点 + 更低低点")
    base_ok = base_depth <= config.max_base_depth
    strength = higher_lows and ema21_rising and bar.close >= ema21

    start = max(0, i - config.swing_lookback + 1)
    swing_low = min(range(start, i + 1), key=lambda k: bars[k].low)
    swing_high = max(range(start, i + 1), key=lambda k: bars[k].high)
    supports: dict[str, float] = {"ema9": ema9, "ema21": ema21, "ema50": ema50}
    if swing_low < i:
        supports["avwap_swing_low"] = item.avwap(swing_low, i) or 0.0
    if swing_high < i:
        supports["avwap_swing_high"] = item.avwap(swing_high, i) or 0.0
    pivot_window = bars[start : i - config.base_sessions + 1]
    if pivot_window:
        supports["prior_pivot"] = max(b.high for b in pivot_window)
    gap = _unfilled_gap_support(bars, i, config.gap_lookback)
    if gap is not None:
        supports["gap"] = gap

    zone = _confluence_zone(supports, bar.close, config)
    zone_bottom, zone_top, zone_members = zone if zone else (None, None, [])
    confluence = len(zone_members)
    turned_up = bar.close > bar.open or (i > 0 and bar.close > bars[i - 1].close)
    triggered = (
        zone_top is not None
        and zone_bottom is not None
        and bar.low <= zone_top
        and bar.close >= zone_top
        and turned_up
    )
    stop_pct = 1.0 - bar.low / bar.close
    prior_high = bars[swing_high].high
    reward_r = (prior_high - bar.close) / (bar.close - bar.low) if bar.close > bar.low else None

    if not leader:
        state = "avoid"
    elif avoid_reasons:
        state = "avoid"
    elif not base_ok:
        state = "leader_no_base"
    elif not strength:
        state = "leader_weak_base"
    elif triggered and confluence >= config.min_confluence and stop_pct <= config.max_stop_pct:
        state = "trigger"
    else:
        state = "setup"

    checks = [
        _check(
            "1",
            "强势股（1/3/6 月涨幅排名前 30%）",
            leader,
            f"1M {momentum['r21']:+.1%} · 3M {momentum['r63']:+.1%} · 6M {momentum['r126']:+.1%}，"
            f"综合分位 {momentum['momentum_pct']:.0%}"
            + ("；满足 Luk 绝对 30% 门槛" if absolute else "；未达 Luk 绝对 30% 门槛"),
        ),
        _check("2", "8 周整理平台（区间 ≤ 25%）", base_ok, f"40 日振幅 {base_depth:.1%}"),
        _check(
            "3",
            "平台内强度（更高低点、21 EMA 上行、站上 21 EMA）",
            strength and not avoid_reasons,
            "；".join(
                avoid_reasons
                or [
                    f"更高低点 {'是' if higher_lows else '否'}",
                    f"21 EMA {'上行' if ema21_rising else '下行'}",
                    f"波动{'收窄' if contraction else '未收窄'}",
                ]
            ),
        ),
        _check(
            "4",
            f"支撑共振 ≥ {config.min_confluence} 且急跌收复",
            state == "trigger",
            (
                f"共振 {confluence} 个（{'、'.join(zone_members)}），距收盘 "
                f"{zone_bottom / bar.close - 1:+.1%} 至 {zone_top / bar.close - 1:+.1%}；"
                if zone_members
                else "附近无共振区；"
            )
            + f"{'今日触及并收复' if triggered else '今日未触发'}；止损 {stop_pct:.1%}",
        ),
    ]
    return {
        "symbol": item.symbol,
        "trade_date": trade_date,
        "state": state,
        "close": bar.close,
        "low": bar.low,
        "stop": bar.low,
        "stop_pct": stop_pct,
        "reward_r": reward_r,
        "momentum": dict(momentum),
        "absolute_momentum": absolute,
        "base_depth": base_depth,
        "higher_lows": higher_lows,
        "ema": {"ema9": ema9, "ema21": ema21, "ema50": ema50},
        "ema_rising": {"ema9": ema9_rising, "ema21": ema21_rising},
        "contraction": contraction,
        "supports": supports,
        "zone": None if zone is None else {"bottom": zone_bottom, "top": zone_top},
        "confluence": confluence,
        "confluence_members": zone_members,
        "triggered": triggered,
        "avoid_reasons": avoid_reasons,
        "anchors": {
            "swing_low": bars[swing_low].trade_date,
            "swing_high": bars[swing_high].trade_date,
        },
        "checks": checks,
    }


def screen(
    series: Mapping[str, SymbolSeries],
    trade_date: str,
    *,
    members: set[str] | None = None,
    config: SetupConfig = SetupConfig(),
) -> list[dict[str, object]]:
    """Analyse every member that traded on ``trade_date``, best setups first."""
    universe = {s: item for s, item in series.items() if members is None or s in members}
    table = momentum_table(universe, trade_date, config)
    results = [
        analyze_at(universe[symbol], trade_date, row, config) for symbol, row in table.items()
    ]
    return sorted(results, key=rank_key)


def rank_key(row: Mapping[str, object]) -> tuple[object, ...]:
    momentum = row.get("momentum") or {}
    return (
        STATE_ORDER.get(str(row["state"]), 9),
        -int(row.get("confluence") or 0),
        float(row.get("stop_pct") or 1.0) if row["state"] == "trigger" else 0.0,
        -float(momentum.get("momentum_pct", 0.0)),  # type: ignore[union-attr]
        str(row["symbol"]),
    )


def _confluence_zone(
    supports: Mapping[str, float], close: float, config: SetupConfig
) -> tuple[float, float, list[str]] | None:
    nearby = sorted(
        (level, name)
        for name, level in supports.items()
        if close * (1 - config.support_window_below)
        <= level
        <= close * (1 + config.support_window_above)
    )
    best: tuple[float, float, list[str]] | None = None
    for start, (low_level, _) in enumerate(nearby):
        members = [
            (level, name)
            for level, name in nearby[start:]
            if level <= low_level * (1 + config.confluence_band)
        ]
        candidate = (low_level, members[-1][0], [name for _, name in members])
        if best is None or (len(candidate[2]), candidate[1]) > (len(best[2]), best[1]):
            best = candidate
    return best


def _unfilled_gap_support(bars: Sequence[Bar], i: int, lookback: int) -> float | None:
    for k in range(i, max(0, i - lookback), -1):
        if (
            bars[k].low > bars[k - 1].high
            and min(b.low for b in bars[k : i + 1]) > bars[k - 1].high
        ):
            return bars[k - 1].high
    return None


def _check(step: str, label: str, passed: bool, detail: str) -> dict[str, object]:
    return {"step": step, "label": label, "passed": bool(passed), "detail": detail}
