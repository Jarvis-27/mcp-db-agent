"""Graceful-shutdown state for the hosted server (G10).

A single ``DrainState`` instance is built in the lifespan startup, shared with
the parent Starlette app, the FastAPI sub-app, and ``src.server``. The
``DrainGuardMiddleware`` registers each ASGI request task on entry and
unregisters on exit; the lifespan exit flips the draining flag, waits for the
registered tasks to drain (up to ``SHUTDOWN_GRACE_PERIOD_SECONDS``), then
cancels stragglers so their ``CancelledError`` handlers can write terminal
``query_history`` rows.
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)


class DrainState:
    """Holds the drain flag and the set of in-flight ASGI request tasks."""

    def __init__(self) -> None:
        self._draining: bool = False
        self._in_flight: set[asyncio.Task] = set()

    @property
    def draining(self) -> bool:
        return self._draining

    @property
    def in_flight_count(self) -> int:
        return len(self._in_flight)

    def begin_drain(self) -> None:
        """Flip the drain flag. Idempotent."""
        self._draining = True

    def register(self, task: asyncio.Task) -> None:
        self._in_flight.add(task)

    def unregister(self, task: asyncio.Task) -> None:
        self._in_flight.discard(task)

    async def wait_for_in_flight(self, timeout_seconds: float) -> int:
        """Wait until all registered tasks complete OR ``timeout_seconds`` elapses.

        Returns the number of tasks still in flight when the wait returned.
        """
        if not self._in_flight:
            return 0
        # Snapshot the set — new requests can no longer be registered because
        # the middleware short-circuits with 503 once ``draining`` is True.
        pending = {t for t in self._in_flight if not t.done()}
        if not pending:
            return 0
        try:
            await asyncio.wait(pending, timeout=timeout_seconds)
        except Exception as exc:
            log.warning("drain_wait_failed", extra={"err": str(exc)})
        return sum(1 for t in pending if not t.done())

    async def cancel_remaining(self, settle_seconds: float = 2.0) -> None:
        """Cancel still-active tasks and await briefly so ``finally`` blocks run.

        Request handlers (notably ``ask_database``) catch ``CancelledError``,
        write a terminal ``query_history`` row, then re-raise. Giving them a
        short settle window after ``task.cancel()`` ensures those writes
        commit before the lifespan tears down the auth engine.
        """
        pending = [t for t in self._in_flight if not t.done()]
        if not pending:
            return
        for task in pending:
            task.cancel()
        try:
            await asyncio.wait(pending, timeout=settle_seconds)
        except Exception as exc:
            log.warning("drain_cancel_failed", extra={"err": str(exc)})
