"""Adaptive network timeout, provider health ordering, and deadline helpers.

Pure-stdlib utility designed for cross-region A-share market data fetches (e.g. fast mainland
connections vs. higher-RTT overseas / UK links). Tracks per-provider rolling EWMA latency and
recent failure/timeout streaks so slow links get enough headroom without stalling forever, and
degraded providers fail over quickly to healthier alternatives.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence, TypeVar

T = TypeVar("T")

DEFAULT_EWMA_ALPHA = 0.35
DEFAULT_COOLDOWN_SECONDS = 120.0


@dataclass
class ProviderStats:
    ewma_latency: float | None = None
    samples: int = 0
    consecutive_failures: int = 0
    last_failure_at: float | None = None
    last_success_at: float | None = None


class ProviderHealthTracker:
    """Thread-safe rolling EWMA latency & failure-cooldown tracker for data providers."""

    def __init__(
        self,
        *,
        ewma_alpha: float = DEFAULT_EWMA_ALPHA,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0.0 < ewma_alpha <= 1.0:
            raise ValueError("ewma_alpha must be in (0, 1]")
        if cooldown_seconds < 0.0:
            raise ValueError("cooldown_seconds must be non-negative")
        self._alpha = float(ewma_alpha)
        self._cooldown = float(cooldown_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        self._stats: dict[str, ProviderStats] = {}

    def record_success(self, provider: str, elapsed_seconds: float) -> None:
        elapsed = max(0.0, float(elapsed_seconds))
        now = self._clock()
        with self._lock:
            st = self._stats.setdefault(provider, ProviderStats())
            if st.ewma_latency is None:
                st.ewma_latency = elapsed
            else:
                st.ewma_latency = self._alpha * elapsed + (1.0 - self._alpha) * st.ewma_latency
            st.samples += 1
            st.consecutive_failures = 0
            st.last_success_at = now

    def record_failure(
        self,
        provider: str,
        elapsed_seconds: float | None = None,
        *,
        timed_out: bool = False,
    ) -> None:
        now = self._clock()
        with self._lock:
            st = self._stats.setdefault(provider, ProviderStats())
            st.consecutive_failures += 1
            st.last_failure_at = now
            # Only nudge latency upward if a timeout occurred on a provider with existing samples
            # so a single fast connection-refused error does not look like "ultra-low latency".
            if timed_out and elapsed_seconds is not None and elapsed_seconds > 0:
                if st.ewma_latency is None:
                    st.ewma_latency = float(elapsed_seconds)
                else:
                    st.ewma_latency = max(
                        st.ewma_latency,
                        self._alpha * float(elapsed_seconds) + (1.0 - self._alpha) * st.ewma_latency,
                    )

    def _in_cooldown_locked(self, st: ProviderStats | None, now: float) -> bool:
        if st is None or st.consecutive_failures <= 0 or st.last_failure_at is None:
            return False
        return (now - st.last_failure_at) < self._cooldown

    def _global_latency_locked(self) -> float | None:
        latencies = sorted(
            st.ewma_latency
            for st in self._stats.values()
            if st.ewma_latency is not None and st.samples > 0
        )
        if not latencies:
            return None
        mid = len(latencies) // 2
        if len(latencies) % 2 == 1:
            return latencies[mid]
        return 0.5 * (latencies[mid - 1] + latencies[mid])

    def adaptive_timeout(
        self,
        provider: str,
        base_timeout: float,
        *,
        min_timeout: float | None = None,
        max_timeout: float | None = None,
    ) -> float:
        """Compute an adaptive per-attempt timeout bounded to ``[min_timeout, max_timeout]``.

        - Fast mainland links (low EWMA latency) stay near ``1x base_timeout``.
        - Slower cross-border/UK links smoothly scale up to give legitimate slow requests room.
        - Providers currently in failure cooldown are capped at ``base_timeout`` so failover stays
          fast instead of waiting longer on a broken endpoint.
        """
        base = max(0.05, float(base_timeout))
        lo = max(0.05, float(min_timeout)) if min_timeout is not None else max(0.05, base * 0.6)
        hi = max(lo, float(max_timeout)) if max_timeout is not None else max(base, base * 2.2)
        now = self._clock()
        with self._lock:
            st = self._stats.get(provider)
            in_cooldown = self._in_cooldown_locked(st, now)
            lat = st.ewma_latency if (st is not None and st.samples > 0) else None
            if lat is None:
                lat = self._global_latency_locked()

        if in_cooldown:
            return max(lo, min(hi, base))
        if lat is None:
            return max(lo, min(hi, base))

        scaled = max(base, lat * 3.0 + base * 0.5)
        return max(lo, min(hi, scaled))

    def ordered_providers(self, candidates: Sequence[str]) -> list[str]:
        """Rank equivalent providers by health (non-cooldown first) and lower EWMA latency.

        Preserves the original candidate order when providers are healthy and not all have been
        measured yet, so primary providers with richer schemas are not abandoned unnecessarily.
        """
        items = list(candidates)
        if len(items) <= 1:
            return items
        now = self._clock()
        with self._lock:
            healthy: list[tuple[int, str, float | None]] = []
            degraded: list[tuple[int, str, int, float]] = []
            for idx, name in enumerate(items):
                st = self._stats.get(name)
                if self._in_cooldown_locked(st, now):
                    assert st is not None and st.last_failure_at is not None
                    degraded.append((idx, name, st.consecutive_failures, st.last_failure_at))
                else:
                    lat = st.ewma_latency if (st is not None and st.samples > 0) else None
                    healthy.append((idx, name, lat))

        if len(healthy) > 1 and all(lat is not None for _, _, lat in healthy):
            healthy.sort(key=lambda entry: (entry[2], entry[0]))  # type: ignore[arg-type]
        else:
            healthy.sort(key=lambda entry: entry[0])

        # Among degraded providers, try fewer consecutive failures / older failures first.
        degraded.sort(key=lambda entry: (entry[2], entry[3], entry[0]))
        return [name for _, name, _ in healthy] + [name for _, name, _, _ in degraded]

    def snapshot(self) -> dict[str, dict[str, object]]:
        with self._lock:
            return {
                name: {
                    "ewma_latency": st.ewma_latency,
                    "samples": st.samples,
                    "consecutive_failures": st.consecutive_failures,
                    "last_failure_at": st.last_failure_at,
                    "last_success_at": st.last_success_at,
                }
                for name, st in self._stats.items()
            }

    def reset(self) -> None:
        with self._lock:
            self._stats.clear()


DEFAULT_TRACKER = ProviderHealthTracker()


def adaptive_timeout(
    provider: str,
    base_timeout: float,
    *,
    min_timeout: float | None = None,
    max_timeout: float | None = None,
    tracker: ProviderHealthTracker | None = None,
) -> float:
    active = tracker or DEFAULT_TRACKER
    return active.adaptive_timeout(
        provider,
        base_timeout,
        min_timeout=min_timeout,
        max_timeout=max_timeout,
    )


def ordered_providers(
    candidates: Sequence[str],
    *,
    tracker: ProviderHealthTracker | None = None,
) -> list[str]:
    active = tracker or DEFAULT_TRACKER
    return active.ordered_providers(candidates)


def remaining_timeout(deadline: float, *, clock: Callable[[], float] = time.monotonic) -> float:
    """Seconds remaining until ``deadline``, clamped at 0.0."""
    return max(0.0, deadline - clock())


def call_with_timeout(
    fn: Callable[[], T],
    timeout: float,
    *,
    provider: str | None = None,
    tracker: ProviderHealthTracker | None = None,
) -> T:
    """Run ``fn`` in a daemon worker thread with a hard timeout so hung sockets cannot stall.

    When ``provider`` is given, records latency/outcome into ``tracker`` (defaulting to
    ``DEFAULT_TRACKER``).
    """
    active = tracker if tracker is not None else (DEFAULT_TRACKER if provider else None)
    started = time.monotonic()
    result: dict[str, object] = {}

    def _run() -> None:
        try:
            result["value"] = fn()
        except BaseException as exc:  # re-raised in the caller's thread
            result["error"] = exc

    worker = threading.Thread(target=_run, name=f"net-call-{provider or 'anon'}", daemon=True)
    worker.start()
    worker.join(max(0.0, float(timeout)))
    elapsed = time.monotonic() - started

    if worker.is_alive():
        if active is not None and provider:
            active.record_failure(provider, elapsed, timed_out=True)
        raise TimeoutError(f"no response within {timeout:g}s")

    if "error" in result:
        exc = result["error"]
        if active is not None and provider:
            active.record_failure(provider, elapsed, timed_out=isinstance(exc, TimeoutError))
        raise exc  # type: ignore[misc]

    if active is not None and provider:
        active.record_success(provider, elapsed)
    return result.get("value")  # type: ignore[return-value]


def run_parallel_with_deadline(
    tasks: Mapping[str, Callable[[], object]],
    deadline_seconds: float,
    *,
    max_workers: int | None = None,
    provider_prefix: str | None = None,
    tracker: ProviderHealthTracker | None = None,
) -> tuple[dict[str, object], dict[str, BaseException]]:
    """Run ``tasks`` concurrently under one shared wall-clock deadline.

    Returns ``(values, errors)``. Any task still running past ``deadline_seconds`` receives a
    ``TimeoutError`` in ``errors`` without stacking sequential waits. Already-finished tasks are
    always collected even if an earlier key hit the deadline.
    """
    if not tasks:
        return {}, {}
    active = tracker if tracker is not None else (DEFAULT_TRACKER if provider_prefix else None)
    workers = max_workers or min(len(tasks), 8)
    pool = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="net-parallel")
    futures: dict[str, Future[object]] = {}

    def _wrapped(key: str, fn: Callable[[], object]) -> object:
        t0 = time.monotonic()
        prov = f"{provider_prefix}:{key}" if provider_prefix else None
        try:
            value = fn()
        except Exception as exc:
            if active is not None and prov:
                active.record_failure(
                    prov, time.monotonic() - t0, timed_out=isinstance(exc, TimeoutError)
                )
            raise
        if active is not None and prov:
            active.record_success(prov, time.monotonic() - t0)
        return value

    for key, fn in tasks.items():
        futures[key] = pool.submit(_wrapped, key, fn)

    deadline = time.monotonic() + max(0.0, float(deadline_seconds))
    values: dict[str, object] = {}
    errors: dict[str, BaseException] = {}
    try:
        for key, future in futures.items():
            wait_for = remaining_timeout(deadline)
            try:
                values[key] = future.result(timeout=wait_for)
            except (FutureTimeout, TimeoutError) as exc:
                if active is not None and provider_prefix:
                    active.record_failure(
                        f"{provider_prefix}:{key}", float(deadline_seconds), timed_out=True
                    )
                errors[key] = TimeoutError(str(exc) or f"timed out after {deadline_seconds:g}s")
            except BaseException as exc:
                errors[key] = exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return values, errors
