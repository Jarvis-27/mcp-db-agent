"""Per-user in-process sliding-window rate limiter used by the MCP ask_database tool.

This complements the daily quota (which protects long-horizon cost) with a
burst limit (which protects against bursty abuse and absorbs LLM-spend spikes).
Counters are kept in-process and keyed by ``user_id``, so multiple clients of
the same user still share a bucket within a single worker.  For multi-worker
deployments the cap is multiplied by the worker count — see CLAUDE.md
"Rate-limiter scope" for the documented caveat.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque


class PerUserSlidingWindow:
    """Async-safe sliding-window counter keyed on an opaque user identifier."""

    def __init__(self, capacity: int, window_seconds: float) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be a positive integer")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be a positive number")
        self._capacity = capacity
        self._window = float(window_seconds)
        self._buckets: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def window_seconds(self) -> float:
        return self._window

    async def acquire(self, user_id: str) -> tuple[bool, float]:
        """Reserve a slot for *user_id* in the current window.

        Returns ``(allowed, retry_after_seconds)``.  When ``allowed`` is False,
        ``retry_after_seconds`` is the time until the oldest in-window timestamp
        falls off the window (always non-negative).
        """
        async with self._lock:
            now = time.monotonic()
            bucket = self._buckets.setdefault(user_id, deque())
            cutoff = now - self._window
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self._capacity:
                retry_after = self._window - (now - bucket[0])
                return False, max(retry_after, 0.0)
            bucket.append(now)
            return True, 0.0
