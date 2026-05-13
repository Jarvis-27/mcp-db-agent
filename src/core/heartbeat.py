"""Async heartbeat used by /health/live to detect a stuck event loop (G1).

A background task updates ``_last_tick`` on every loop iteration.  When the
gap between ``time.monotonic()`` and ``_last_tick`` grows past ``stale_after``
the loop is wedged (deadlocked thread pool, GIL-bound C call, slow GC pause)
and ``/health/live`` should report 503 so the orchestrator can replace the
worker.
"""

from __future__ import annotations

import asyncio
import time


class HeartbeatMonitor:
    """Tracks freshness of an event-loop tick.

    The monitor itself does not own scheduling; ``start()`` schedules a
    background task that updates the tick.  In tests you can construct the
    monitor without calling ``start()`` and drive ``_last_tick`` directly.
    """

    def __init__(self, interval_seconds: float = 1.0, stale_after_seconds: float = 5.0) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if stale_after_seconds <= interval_seconds:
            raise ValueError("stale_after_seconds must be greater than interval_seconds")
        self._interval = interval_seconds
        self._stale_after = stale_after_seconds
        self._last_tick: float = time.monotonic()
        self._task: asyncio.Task | None = None

    @property
    def stale_after_seconds(self) -> float:
        return self._stale_after

    def is_alive(self) -> bool:
        return (time.monotonic() - self._last_tick) <= self._stale_after

    def seconds_since_last_tick(self) -> float:
        return time.monotonic() - self._last_tick

    async def _tick_loop(self) -> None:
        while True:
            self._last_tick = time.monotonic()
            await asyncio.sleep(self._interval)

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._last_tick = time.monotonic()
        self._task = asyncio.create_task(self._tick_loop(), name="heartbeat-tick")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
