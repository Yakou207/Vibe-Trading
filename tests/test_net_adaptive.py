from __future__ import annotations

import threading
import time
from datetime import date
from pathlib import Path

import pytest

from fintech_quant.data.net_adaptive import (
    ProviderHealthTracker,
    call_with_timeout,
    run_parallel_with_deadline,
)
from fintech_quant.information.stock_intel import collect_stock_intel
from fintech_quant.reports.live_stock import LiveContext, analyze_live
from test_momentum_setup import _leader_with_flush


class _FakeClock:
    def __init__(self, start: float = 100.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_adaptive_timeout_scales_for_slow_links_and_bounds_to_min_max() -> None:
    clock = _FakeClock()
    tracker = ProviderHealthTracker(clock=clock)

    # Unmeasured provider returns base_timeout clamped to [min, max].
    assert tracker.adaptive_timeout("sina", 10.0, min_timeout=6.0, max_timeout=25.0) == pytest.approx(10.0)

    # Fast mainland latency (~0.3s) stays right around 1x base_timeout.
    tracker.record_success("sina", 0.3)
    tracker.record_success("sina", 0.25)
    assert tracker.adaptive_timeout("sina", 10.0, min_timeout=6.0, max_timeout=25.0) == pytest.approx(10.0)

    # Cross-border/UK slow latency (~5.0s) scales up smoothly above base_timeout.
    for _ in range(5):
        tracker.record_success("eastmoney", 5.0)
    uk_timeout = tracker.adaptive_timeout("eastmoney", 10.0, min_timeout=6.0, max_timeout=25.0)
    assert 15.0 < uk_timeout <= 25.0

    # Extreme latency is capped cleanly at max_timeout.
    for _ in range(5):
        tracker.record_success("slow_ep", 20.0)
    assert tracker.adaptive_timeout("slow_ep", 10.0, min_timeout=6.0, max_timeout=25.0) == pytest.approx(25.0)

    # A failing provider in cooldown does NOT get inflated timeout — fail over fast.
    tracker.record_failure("eastmoney", 12.0, timed_out=True)
    assert tracker.adaptive_timeout("eastmoney", 10.0, min_timeout=6.0, max_timeout=25.0) == pytest.approx(10.0)


def test_adaptive_timeout_uses_global_median_for_unseen_provider() -> None:
    clock = _FakeClock()
    tracker = ProviderHealthTracker(clock=clock)
    tracker.record_success("sina", 5.0)
    tracker.record_success("tencent", 6.0)

    # An unseen provider inherits cross-provider latency signal on slow links.
    assert tracker.adaptive_timeout("new_source", 10.0, min_timeout=6.0, max_timeout=25.0) > 15.0


def test_ordered_providers_failover_latency_ranking_and_cooldown_recovery() -> None:
    clock = _FakeClock()
    tracker = ProviderHealthTracker(cooldown_seconds=60.0, clock=clock)

    # Initial order preserved when no samples exist.
    assert tracker.ordered_providers(("sina", "tencent")) == ["sina", "tencent"]

    # When primary fails, healthy fallback moves to the front immediately.
    tracker.record_failure("sina", 8.0, timed_out=True)
    assert tracker.ordered_providers(("sina", "tencent")) == ["tencent", "sina"]

    # After cooldown expires, sina is no longer deprioritized as degraded.
    clock.advance(61.0)
    assert tracker.ordered_providers(("sina", "tencent")) == ["sina", "tencent"]

    # When both healthy providers have measured EWMA latency, the faster one wins.
    tracker.record_success("sina", 4.5)
    tracker.record_success("tencent", 0.4)
    assert tracker.ordered_providers(("sina", "tencent")) == ["tencent", "sina"]

    # If sina speeds up and becomes faster, it reclaims first place.
    for _ in range(10):
        tracker.record_success("sina", 0.15)
    assert tracker.ordered_providers(("sina", "tencent")) == ["sina", "tencent"]


def test_call_with_timeout_records_success_timeout_and_error() -> None:
    tracker = ProviderHealthTracker()
    release = threading.Event()

    assert call_with_timeout(lambda: 42, 1.0, provider="fast", tracker=tracker) == 42
    assert tracker.snapshot()["fast"]["samples"] == 1
    assert tracker.snapshot()["fast"]["consecutive_failures"] == 0

    def hung() -> int:
        release.wait(5.0)
        return 1

    try:
        with pytest.raises(TimeoutError):
            call_with_timeout(hung, 0.05, provider="hung_src", tracker=tracker)
    finally:
        release.set()
    assert tracker.snapshot()["hung_src"]["consecutive_failures"] == 1

    with pytest.raises(RuntimeError, match="boom"):
        call_with_timeout(
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
            1.0,
            provider="broken",
            tracker=tracker,
        )
    assert tracker.snapshot()["broken"]["consecutive_failures"] == 1


def test_shared_deadline_does_not_stack_and_collects_fast_tasks() -> None:
    release = threading.Event()

    def slow() -> list[dict[str, object]]:
        release.wait(5.0)
        return []

    def fast() -> list[dict[str, object]]:
        return [{"ok": True}]

    tasks = {
        "hung_1": slow,
        "hung_2": slow,
        "hung_3": slow,
        "hung_4": slow,
        "fast_after_hung": fast,
    }
    started = time.monotonic()
    try:
        values, errors = run_parallel_with_deadline(tasks, deadline_seconds=0.12)
    finally:
        release.set()
    elapsed = time.monotonic() - started

    # Shared deadline: 4 hung tasks must NOT stack to 4 * 0.12 = 0.48s.
    assert elapsed < 0.35
    assert values["fast_after_hung"] == [{"ok": True}]
    for key in ("hung_1", "hung_2", "hung_3", "hung_4"):
        assert isinstance(errors[key], TimeoutError)


def test_stock_intel_uses_shared_wall_clock_deadline() -> None:
    release = threading.Event()

    def slow(_code: str) -> list[dict[str, object]]:
        release.wait(5.0)
        return []

    def fast_news(_code: str) -> list[dict[str, object]]:
        return [{"新闻标题": "测试快讯", "发布时间": "2026-11-22 09:00:00"}]

    fetchers = {
        "notices": slow,
        "research": slow,
        "comment_score": slow,
        "financials": slow,
        "news": fast_news,
    }
    started = time.monotonic()
    try:
        payload = collect_stock_intel(
            "601398.SH",
            today=date(2026, 11, 22),
            cache_dir=None,
            fetchers=fetchers,
            timeout=0.12,
        )
    finally:
        release.set()
    elapsed = time.monotonic() - started

    assert elapsed < 0.35
    assert payload["sources"]["news"]["status"] == "ok"
    assert payload["sources"]["notices"]["status"] == "timeout"
    assert payload["sources"]["financials"]["status"] == "timeout"
    assert len(payload["items"]) == 1


def test_analyze_live_parallelizes_bars_valuation_and_financials(tmp_path: Path) -> None:
    bars = [
        {
            "date": b.trade_date,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
        }
        for b in _leader_with_flush().bars
    ]

    def slow_bars(**_kw):
        time.sleep(0.12)
        return bars

    def slow_value(**_kw):
        time.sleep(0.12)
        return [{"数据日期": "2026-10-19", "PE(TTM)": 15.0, "市净率": 2.0}]

    def slow_fin(**_kw):
        time.sleep(0.12)
        return [{"报告期": "2026-06-30", "净资产收益率": "8.0%", "营业总收入同比增长率": "12.0%"}]

    ctx = LiveContext(
        cache_dir=tmp_path,
        today=date(2026, 10, 20),
        fetchers={"sina": slow_bars, "value": slow_value, "financials": slow_fin},
    )
    started = time.monotonic()
    result = analyze_live(ctx, "300624.SZ", {}, fresh=False)
    elapsed = time.monotonic() - started

    # Sequential would be >= 0.36s; parallel should complete close to 0.12s.
    assert elapsed < 0.28
    assert result["source"] == "sina"
    assert result["fundamentals"]["pe"] == pytest.approx(15.0)
    assert result["fundamentals"]["roe"] == pytest.approx(0.16)
    assert isinstance(result["fetch_ms"], int) and result["fetch_ms"] >= 100
