"""Token-bucket rate limiter for source-keyed task throughput (ADR-017 §4).

A `TokenBucket` enforces an upper bound on requests-per-second to a single
upstream source while permitting short bursts. Tasks share a process-wide
bucket per source name, so a chunked yfinance task and a chunked
companyfacts task running in parallel cannot collectively exceed SEC's
fair-use rate.

Usage::

    from data.rate_limit import bucket_for

    bucket = bucket_for("sec")
    async with httpx.AsyncClient() as client:
        await bucket.acquire()
        r = await client.get(url)

The runner (``screener.tasks.runner.run_task``) passes the right bucket to
``FilterTask.fetch_chunk`` based on the task's declared ``source``.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from threading import Lock as _ThreadLock


@dataclass
class TokenBucket:
    """Hybrid sync+async token bucket: ``rate`` tokens added per second,
    capped at ``burst``.

    Both ``acquire()`` (async) and ``acquire_sync()`` (sync, for use from
    threadpool workers like asyncio.run_in_executor) are provided. State
    is guarded by a ``threading.Lock`` so the two access paths can safely
    share one bucket — the polygon client is sync inside an executor
    thread, while future async clients can hit the same bucket.
    """

    rate: float                                  # tokens per second
    burst: int                                   # max simultaneous tokens
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)
    _lock: _ThreadLock = field(init=False, default_factory=_ThreadLock)

    def __post_init__(self) -> None:
        if self.rate <= 0:
            raise ValueError(f"TokenBucket rate must be positive, got {self.rate}")
        if self.burst < 1:
            raise ValueError(f"TokenBucket burst must be ≥1, got {self.burst}")
        self._tokens = float(self.burst)
        self._last_refill = time.monotonic()

    def _try_consume(self, n: int) -> float:
        """Return 0.0 if `n` tokens were consumed; else seconds to wait."""
        with self._lock:
            self._refill()
            if self._tokens >= n:
                self._tokens -= n
                return 0.0
            deficit = n - self._tokens
            return deficit / self.rate

    async def acquire(self, n: int = 1) -> None:
        """Async: block until ``n`` tokens are available, then consume them."""
        if n > self.burst:
            raise ValueError(
                f"acquire({n}) exceeds bucket burst {self.burst} — would deadlock"
            )
        while True:
            wait = self._try_consume(n)
            if wait <= 0:
                return
            await asyncio.sleep(wait)

    def acquire_sync(self, n: int = 1, timeout: float | None = None) -> bool:
        """Sync: block until ``n`` tokens are available. Used from executor threads.

        Returns True on success, False if `timeout` was set and exceeded.
        """
        if n > self.burst:
            raise ValueError(
                f"acquire_sync({n}) exceeds bucket burst {self.burst} — would deadlock"
            )
        deadline = (time.monotonic() + timeout) if timeout is not None else None
        while True:
            wait = self._try_consume(n)
            if wait <= 0:
                return True
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                wait = min(wait, remaining)
            time.sleep(wait)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now
        self._tokens = min(self.burst, self._tokens + elapsed * self.rate)


# ── Process-wide singletons keyed by FilterTask.source ───────────────────
# Conservative defaults; tune per source as data is collected.
#   • SEC: 10 req/sec is the documented free limit, but SEC tracks bursts
#     over longer windows than 1s. Sustained bulk drains at 8/sec trip
#     a soft IP-block. 2.5/sec with small burst is the empirically safe
#     ceiling for multi-hour drains.
#   • FMP: 250 req/day on free tier — rate alone won't enforce daily budget,
#     but 4/sec keeps short-run throughput safe
#   • yfinance: Yahoo's anti-abuse layer bans us above 1 req/sec sustained
SEC_BUCKET = TokenBucket(rate=2.5, burst=5)
FMP_BUCKET = TokenBucket(rate=4.0, burst=8)
YF_BUCKET = TokenBucket(rate=1.0, burst=2)
# Polygon free tier: 5 requests / minute = 5/60 per second, burst 5.
# Per ADR-019 §3, this is the dominant bound on dive + watchlist usage.
POLYGON_BUCKET = TokenBucket(rate=5.0 / 60.0, burst=5)

_BUCKETS: dict[str, TokenBucket] = {
    "sec": SEC_BUCKET,
    "fmp": FMP_BUCKET,
    "yf": YF_BUCKET,
    "polygon": POLYGON_BUCKET,
    "in-memory": TokenBucket(rate=1_000_000.0, burst=1_000_000),  # effectively unlimited
}


def bucket_for(source: str) -> TokenBucket:
    """Lookup the shared bucket for a FilterTask source name.

    Raises ``KeyError`` for unknown sources — fail loud rather than
    silently bypass rate limits.
    """
    try:
        return _BUCKETS[source]
    except KeyError as e:
        raise KeyError(
            f"No TokenBucket registered for source={source!r}. "
            f"Known sources: {sorted(_BUCKETS)}"
        ) from e
