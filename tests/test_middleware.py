"""Tests for ApiKeyMiddleware — auth, ContextVar scoping, cache."""

from unittest.mock import MagicMock

import pytest
from cachetools import TTLCache

from src.auth.middleware import ApiKeyMiddleware, user_config_var
from src.auth.user_store import UserConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(user_id: str = "user-1") -> UserConfig:
    return UserConfig(
        user_id=user_id,
        database_url="sqlite:///./demo.db",
        is_active=True,
    )


def _make_store(user: UserConfig | None) -> MagicMock:
    store = MagicMock()
    store.get_user_by_api_key.return_value = user
    return store


async def _collect_response(app, scope):
    """Run an ASGI app and collect the response status + body."""
    received = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        received.append(message)

    await app(scope, receive, send)
    start = next(m for m in received if m["type"] == "http.response.start")
    body = next(m for m in received if m["type"] == "http.response.body")
    return start["status"], body.get("body", b"")


def _http_scope(headers: list[tuple[bytes, bytes]]) -> dict:
    return {
        "type": "http",
        "method": "GET",
        "path": "/mcp/",
        "headers": headers,
    }


# ---------------------------------------------------------------------------
# Missing key → 401
# ---------------------------------------------------------------------------


async def test_missing_key_returns_401():
    store = _make_store(None)
    cache = TTLCache(maxsize=100, ttl=60)

    async def inner_app(scope, receive, send):
        raise AssertionError("should not be called")

    mw = ApiKeyMiddleware(inner_app, store, cache)
    status, body = await _collect_response(mw, _http_scope([]))
    assert status == 401
    assert b"Missing" in body


# ---------------------------------------------------------------------------
# X-API-Key header accepted
# ---------------------------------------------------------------------------


async def test_x_api_key_header_accepted():
    user = _make_user()
    store = _make_store(user)
    cache = TTLCache(maxsize=100, ttl=60)
    seen_config = []

    async def inner_app(scope, receive, send):
        seen_config.append(user_config_var.get())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = ApiKeyMiddleware(inner_app, store, cache)
    scope = _http_scope([(b"x-api-key", b"mdbk_test_key")])
    status, _ = await _collect_response(mw, scope)
    assert status == 200
    assert seen_config[0] is user


# ---------------------------------------------------------------------------
# Authorization: Bearer accepted
# ---------------------------------------------------------------------------


async def test_bearer_token_accepted():
    user = _make_user()
    store = _make_store(user)
    cache = TTLCache(maxsize=100, ttl=60)
    seen_config = []

    async def inner_app(scope, receive, send):
        seen_config.append(user_config_var.get())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = ApiKeyMiddleware(inner_app, store, cache)
    scope = _http_scope([(b"authorization", b"Bearer mdbk_test_key")])
    status, _ = await _collect_response(mw, scope)
    assert status == 200
    assert seen_config[0] is user


# ---------------------------------------------------------------------------
# Invalid key → 401
# ---------------------------------------------------------------------------


async def test_invalid_key_returns_401():
    store = _make_store(None)  # key not found
    cache = TTLCache(maxsize=100, ttl=60)

    async def inner_app(scope, receive, send):
        raise AssertionError("should not be called")

    mw = ApiKeyMiddleware(inner_app, store, cache)
    scope = _http_scope([(b"x-api-key", b"mdbk_wrong")])
    status, _ = await _collect_response(mw, scope)
    assert status == 401


# ---------------------------------------------------------------------------
# ContextVar reset after exception in inner app
# ---------------------------------------------------------------------------


async def test_context_var_reset_on_exception():
    user = _make_user()
    store = _make_store(user)
    cache = TTLCache(maxsize=100, ttl=60)

    async def inner_app(scope, receive, send):
        raise RuntimeError("inner app exploded")

    mw = ApiKeyMiddleware(inner_app, store, cache)
    scope = _http_scope([(b"x-api-key", b"mdbk_test_key")])

    with pytest.raises(RuntimeError, match="inner app exploded"):
        await mw(scope, None, None)

    # ContextVar must be reset to its default even after the exception
    assert user_config_var.get() is None


# ---------------------------------------------------------------------------
# Cache hit avoids store lookup
# ---------------------------------------------------------------------------


async def test_cache_hit_skips_store_lookup():
    user = _make_user()
    store = _make_store(user)
    cache = TTLCache(maxsize=100, ttl=60)

    async def inner_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = ApiKeyMiddleware(inner_app, store, cache)
    scope = _http_scope([(b"x-api-key", b"mdbk_test_key")])

    # First request — populates cache
    await _collect_response(mw, scope)
    # Second request — should hit cache
    await _collect_response(mw, scope)

    # Store should only be called once
    assert store.get_user_by_api_key.call_count == 1


# ---------------------------------------------------------------------------
# Non-HTTP scopes pass through without auth
# ---------------------------------------------------------------------------


async def test_non_http_scope_passes_through():
    store = _make_store(None)
    cache = TTLCache(maxsize=100, ttl=60)
    passed = []

    async def inner_app(scope, receive, send):
        passed.append(scope["type"])

    mw = ApiKeyMiddleware(inner_app, store, cache)
    await mw({"type": "lifespan"}, None, None)
    assert passed == ["lifespan"]
