"""ASGI middleware for API key authentication and per-request user scoping."""

import hashlib
import json
from contextvars import ContextVar
from typing import Callable

from cachetools import TTLCache

from src.auth.user_store import UserConfig, UserStore

# ContextVar set per-request by ApiKeyMiddleware and reset in the finally block.
# Tools in server.py read this to get the current user's configuration.
user_config_var: ContextVar[UserConfig | None] = ContextVar("user_config", default=None)


def _extract_api_key(headers: list[tuple[bytes, bytes]]) -> str | None:
    """Extract the raw API key from request headers.

    Accepts both:
      X-API-Key: mdbk_...
      Authorization: Bearer mdbk_...
    """
    for name, value in headers:
        name_lower = name.lower()
        if name_lower == b"x-api-key":
            return value.decode("utf-8", errors="replace").strip()
        if name_lower == b"authorization":
            val = value.decode("utf-8", errors="replace").strip()
            if val.lower().startswith("bearer "):
                return val[7:].strip()
    return None


async def _send_401(send: Callable, message: str) -> None:
    body = json.dumps({"detail": message}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class ApiKeyMiddleware:
    """Pure ASGI middleware that authenticates requests via API key.

    - Reads the key from X-API-Key or Authorization: Bearer headers.
    - Caches lookups (keyed on sha256(key), never the raw key) for 60 s.
    - Sets user_config_var on the ContextVar for the duration of the request.
    - Resets the ContextVar in a finally block — exception-safe.
    """

    def __init__(
        self,
        app,
        user_store: UserStore,
        cache: TTLCache,
    ) -> None:
        self._app = app
        self._user_store = user_store
        self._cache = cache

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        raw_key = _extract_api_key(scope.get("headers", []))
        if raw_key is None:
            await _send_401(send, "Missing API key")
            return

        # Cache key is sha256(raw_key) — never hold the raw key in memory
        cache_key = hashlib.sha256(raw_key.encode()).hexdigest()
        user_config: UserConfig | None = self._cache.get(cache_key)
        if user_config is None:
            user_config = self._user_store.get_user_by_api_key(raw_key)
            if user_config is None:
                await _send_401(send, "Invalid or inactive API key")
                return
            self._cache[cache_key] = user_config

        token = user_config_var.set(user_config)
        try:
            await self._app(scope, receive, send)
        finally:
            user_config_var.reset(token)
