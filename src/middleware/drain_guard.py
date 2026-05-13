"""ASGI middleware that refuses new requests during graceful shutdown (G10).

Once ``DrainState.draining`` is True, every HTTP request returns 503 with a
structured JSON body — except liveness / readiness probes, which keep working
so the orchestrator can observe the worker finishing its in-flight work.
While not draining, each request task is registered with the drain state so
the lifespan exit can wait for them and (if grace expires) cancel them so
their ``finally`` blocks can log terminal ``query_history`` rows.
"""

from __future__ import annotations

import asyncio
import json

from src.core.drain import DrainState

_DRAIN_503_BODY = json.dumps(
    {
        "error": "Service is shutting down",
        "code": "service_draining",
        "retry_after_seconds": 30,
        "suggestion": "Retry in a few moments — a new worker will pick up the request.",
    }
).encode()

_DRAIN_503_HEADERS = [
    (b"content-type", b"application/json"),
    (b"content-length", str(len(_DRAIN_503_BODY)).encode()),
    (b"retry-after", b"30"),
]


class DrainGuardMiddleware:
    """Sits on the parent Starlette app, after RequestIDMiddleware."""

    # Paths that must keep working during drain so orchestrators can observe
    # the worker. The api sub-app is mounted at /api, so the actual incoming
    # paths are /api/health/live and /api/health/ready — we match on suffix.
    _ALLOWED_PATH_SUFFIXES = ("/health/live", "/health/ready")

    def __init__(self, app, *, drain_state: DrainState) -> None:
        self._app = app
        self._drain_state = drain_state

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        path: str = scope.get("path", "") or ""

        if self._drain_state.draining and not self._is_drain_exempt(path):
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": list(_DRAIN_503_HEADERS),
                }
            )
            await send({"type": "http.response.body", "body": _DRAIN_503_BODY})
            return

        task = asyncio.current_task()
        if task is not None:
            self._drain_state.register(task)
        try:
            await self._app(scope, receive, send)
        finally:
            if task is not None:
                self._drain_state.unregister(task)

    @classmethod
    def _is_drain_exempt(cls, path: str) -> bool:
        return any(path.endswith(suffix) for suffix in cls._ALLOWED_PATH_SUFFIXES)
