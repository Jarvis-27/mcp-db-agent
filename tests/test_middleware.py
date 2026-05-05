"""Tests for ApiKeyMiddleware — auth, ContextVar scoping, cache."""

from unittest.mock import MagicMock

import pytest
from cachetools import TTLCache
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from src.api.app import api_app
from src.auth.crypto import CredentialCipher
from src.auth.middleware import ApiKeyMiddleware, user_config_var
from src.auth.onboarding import ACCOUNT_SUSPENDED
from src.auth.token_store import TokenStore
from src.auth.user_store import Base, UserConfig, UserStore
from src.email_sender import LogEmailSender


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(user_id: str = "user-1") -> UserConfig:
    return UserConfig(
        user_id=user_id,
        database_url="sqlite:///./demo.db",
        is_active=True,
        onboarding_status="active",
        email=None,
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


async def test_suspended_user_loses_mcp_access():
    """After account suspension (cache cleared), MCP access is denied."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    cipher = CredentialCipher([Fernet.generate_key().decode()])
    store = UserStore(engine, cipher)
    token_store = TokenStore(engine)
    auth_cache = TTLCache(maxsize=100, ttl=60)

    try:
        api_app.state.user_store = store
        api_app.state.cipher = cipher
        api_app.state.token_store = token_store
        api_app.state.email_sender = LogEmailSender()
        api_app.state.auth_key_cache = auth_cache
        api_app.state.user_session_cache = TTLCache(maxsize=100, ttl=60)
        api_app.state.factory = None

        # Create active user with API key
        user_id = store.create_user("mcp-suspend@example.com")
        store.set_email_verified(user_id)
        store.transition_user_state(user_id, "pending_db_connection")
        store.upsert_user_database(user_id, cipher.encrypt("postgresql://user:pass@8.8.8.8/db"))
        store.activate_user(user_id)
        raw_key, _ = store.create_api_key(
            user_id=user_id,
            name="default",
            scopes=["mcp_read"],
        )

        async def inner_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        mw = ApiKeyMiddleware(inner_app, store, auth_cache)
        scope = _http_scope([(b"x-api-key", raw_key.encode())])

        # First request succeeds and populates cache
        first_status, _ = await _collect_response(mw, scope)
        assert first_status == 200
        assert len(auth_cache) == 1

        # Suspend the user and manually clear the cache (simulating a suspension event)
        store.set_account_status(user_id, ACCOUNT_SUSPENDED)
        auth_cache.clear()

        # Next request must fail because the store now returns None for suspended users
        second_status, body = await _collect_response(mw, scope)
        assert second_status == 401
        assert b"Invalid or inactive API key" in body
    finally:
        engine.dispose()
