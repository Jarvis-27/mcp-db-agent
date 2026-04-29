"""Unit tests for OAuthMCPTokenVerifier, HybridMCPTokenVerifier, and
UserConfigResetMiddleware in src.auth.mcp_token_verifiers."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cachetools import TTLCache
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser, RequireAuthMiddleware
from starlette.authentication import AuthCredentials

from src.auth.mcp_token_verifiers import (
    HybridMCPTokenVerifier,
    OAuthMCPTokenVerifier,
    UserConfigResetMiddleware,
    _ucv_reset_token_var,
)
from src.auth.middleware import user_config_var
from src.auth.oauth_identity import OAuthIdentityError
from src.auth.oauth_verifier import OAuthClaims, OAuthVerificationError
from src.auth.user_store import UserConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(user_id: str = "u-1", scopes: frozenset[str] | None = None) -> UserConfig:
    return UserConfig(
        user_id=user_id,
        database_url="sqlite:///./demo.db",
        is_active=True,
        onboarding_status="setup_complete",
        email="test@example.com",
        scopes=scopes or frozenset({"mcp_read"}),
    )


def _make_claims(expires_at: int | None = None) -> OAuthClaims:
    return OAuthClaims(
        issuer="https://auth.example.com",
        subject="oauth2|user123",
        scopes=frozenset({"mcp:access"}),
        expires_at=expires_at or int(time.time()) + 3600,
    )


def _make_verifier(*, raises: Exception | None = None, claims: OAuthClaims | None = None):
    m = MagicMock()
    if raises:
        m.verify.side_effect = raises
    else:
        m.verify.return_value = claims or _make_claims()
    return m


def _make_resolver(*, raises: Exception | None = None, user: UserConfig | None = None):
    m = MagicMock()
    if raises:
        m.resolve.side_effect = raises
    else:
        m.resolve.return_value = user or _make_user()
    return m


def _make_store(*, user: UserConfig | None = None):
    m = MagicMock()
    m.get_user_by_api_key.return_value = user
    return m


async def _run(middleware, headers: list[tuple[bytes, bytes]]) -> tuple[int, bytes, dict]:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp/",
        "headers": headers,
    }
    received: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(msg):
        received.append(msg)

    await middleware(scope, receive, send)
    start = next(m for m in received if m["type"] == "http.response.start")
    body_msg = next(m for m in received if m["type"] == "http.response.body")
    resp_headers = {k.decode(): v.decode() for k, v in start.get("headers", [])}
    return start["status"], body_msg.get("body", b""), resp_headers


async def _noop_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b""})


async def _require_auth_status(access_token, required_scopes: list[str]) -> int:
    received: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(msg):
        received.append(msg)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp/",
        "headers": [],
        "user": AuthenticatedUser(access_token),
        "auth": AuthCredentials(access_token.scopes),
    }
    middleware = RequireAuthMiddleware(_noop_app, required_scopes)
    await middleware(scope, receive, send)
    start = next(m for m in received if m["type"] == "http.response.start")
    return int(start["status"])


# ---------------------------------------------------------------------------
# OAuthMCPTokenVerifier
# ---------------------------------------------------------------------------


async def test_oauth_verifier_valid_token_returns_access_token():
    user = _make_user("u-42")
    claims = _make_claims(expires_at=9999999999)
    verifier = _make_verifier(claims=claims)
    resolver = _make_resolver(user=user)

    tv = OAuthMCPTokenVerifier(verifier=verifier, resolver=resolver)
    with patch("src.auth.mcp_token_verifiers.asyncio.to_thread", new=AsyncMock(side_effect=[claims, user])):
        result = await tv.verify_token("jwt.token.here")

    assert result is not None
    assert result.client_id == "u-42"
    assert result.expires_at == 9999999999
    assert "mcp:access" in result.scopes


async def test_oauth_verifier_sets_user_config_var():
    user = _make_user("u-42")
    claims = _make_claims()
    tv = OAuthMCPTokenVerifier(verifier=_make_verifier(claims=claims), resolver=_make_resolver(user=user))

    with patch("src.auth.mcp_token_verifiers.asyncio.to_thread", new=AsyncMock(side_effect=[claims, user])):
        result = await tv.verify_token("jwt.token.here")

    assert result is not None
    assert user_config_var.get() is user

    # Cleanup
    reset_token = _ucv_reset_token_var.get()
    if reset_token is not None:
        user_config_var.reset(reset_token)


async def test_oauth_verifier_bad_jwt_returns_none():
    verifier = _make_verifier(raises=OAuthVerificationError("bad sig"))
    resolver = _make_resolver()

    tv = OAuthMCPTokenVerifier(verifier=verifier, resolver=resolver)
    with patch("src.auth.mcp_token_verifiers.asyncio.to_thread", new=AsyncMock(side_effect=OAuthVerificationError("bad sig"))):
        result = await tv.verify_token("bad.token")

    assert result is None
    assert user_config_var.get() is None


async def test_oauth_verifier_no_linked_account_returns_none():
    claims = _make_claims()
    verifier = _make_verifier(claims=claims)
    resolver = _make_resolver(raises=OAuthIdentityError("no account", code="no_linked_account"))

    tv = OAuthMCPTokenVerifier(verifier=verifier, resolver=resolver)
    with patch(
        "src.auth.mcp_token_verifiers.asyncio.to_thread",
        new=AsyncMock(side_effect=[claims, OAuthIdentityError("no account", code="no_linked_account")]),
    ):
        result = await tv.verify_token("jwt.token.here")

    assert result is None
    assert user_config_var.get() is None


# ---------------------------------------------------------------------------
# HybridMCPTokenVerifier
# ---------------------------------------------------------------------------


async def test_hybrid_routes_api_key_by_prefix():
    user = _make_user()
    store = _make_store(user=user)
    verifier = _make_verifier()
    resolver = _make_resolver()
    cache: TTLCache = TTLCache(maxsize=100, ttl=60)

    tv = HybridMCPTokenVerifier(verifier=verifier, resolver=resolver, user_store=store, api_key_cache=cache)
    with patch("src.auth.mcp_token_verifiers.asyncio.to_thread", new=AsyncMock(return_value=user)):
        result = await tv.verify_token("mdbk_some_key")

    assert result is not None
    assert result.client_id == user.user_id
    verifier.verify.assert_not_called()

    # Cleanup
    reset_token = _ucv_reset_token_var.get()
    if reset_token is not None:
        user_config_var.reset(reset_token)


async def test_hybrid_api_key_scopes_pass_fastmcp_required_scope_check():
    user = _make_user(scopes=frozenset({"mcp_read"}))
    store = _make_store(user=user)
    cache: TTLCache = TTLCache(maxsize=100, ttl=60)

    tv = HybridMCPTokenVerifier(
        verifier=_make_verifier(),
        resolver=_make_resolver(),
        user_store=store,
        api_key_cache=cache,
        fastmcp_required_scopes=["mcp:access"],
    )
    with patch("src.auth.mcp_token_verifiers.asyncio.to_thread", new=AsyncMock(return_value=user)):
        result = await tv.verify_token("mdbk_some_key")

    assert result is not None
    assert set(result.scopes) == {"mcp_read", "mcp:access"}
    assert await _require_auth_status(result, ["mcp:access"]) == 200

    # Cleanup
    reset_token = _ucv_reset_token_var.get()
    if reset_token is not None:
        user_config_var.reset(reset_token)


async def test_hybrid_routes_oauth_by_absence_of_prefix():
    claims = _make_claims()
    user = _make_user()
    store = _make_store(user=None)
    verifier = _make_verifier(claims=claims)
    resolver = _make_resolver(user=user)
    cache: TTLCache = TTLCache(maxsize=100, ttl=60)

    tv = HybridMCPTokenVerifier(verifier=verifier, resolver=resolver, user_store=store, api_key_cache=cache)
    with patch(
        "src.auth.mcp_token_verifiers.asyncio.to_thread",
        new=AsyncMock(side_effect=[claims, user]),
    ):
        result = await tv.verify_token("eyJ.oauth.token")

    assert result is not None
    store.get_user_by_api_key.assert_not_called()

    # Cleanup
    reset_token = _ucv_reset_token_var.get()
    if reset_token is not None:
        user_config_var.reset(reset_token)


async def test_hybrid_api_key_cache_hit():
    user = _make_user()
    store = _make_store(user=user)
    cache: TTLCache = TTLCache(maxsize=100, ttl=60)

    tv = HybridMCPTokenVerifier(
        verifier=_make_verifier(), resolver=_make_resolver(), user_store=store, api_key_cache=cache
    )
    with patch("src.auth.mcp_token_verifiers.asyncio.to_thread", new=AsyncMock(return_value=user)):
        await tv.verify_token("mdbk_key1")

    # Cleanup between calls
    reset_token = _ucv_reset_token_var.get()
    if reset_token is not None:
        user_config_var.reset(reset_token)
    _ucv_reset_token_var.set(None)

    # Second call — should hit cache, store NOT called again
    with patch("src.auth.mcp_token_verifiers.asyncio.to_thread", new=AsyncMock(return_value=user)) as mock_thread:
        await tv.verify_token("mdbk_key1")
        mock_thread.assert_not_called()

    # Cleanup
    reset_token = _ucv_reset_token_var.get()
    if reset_token is not None:
        user_config_var.reset(reset_token)


async def test_hybrid_api_key_missing_scope_returns_none():
    user = _make_user(scopes=frozenset({"other_scope"}))
    store = _make_store(user=user)
    cache: TTLCache = TTLCache(maxsize=100, ttl=60)

    tv = HybridMCPTokenVerifier(
        verifier=_make_verifier(), resolver=_make_resolver(), user_store=store, api_key_cache=cache
    )
    with patch("src.auth.mcp_token_verifiers.asyncio.to_thread", new=AsyncMock(return_value=user)):
        result = await tv.verify_token("mdbk_bad_scope_key")

    assert result is None


async def test_hybrid_api_key_not_found_returns_none():
    store = _make_store(user=None)
    cache: TTLCache = TTLCache(maxsize=100, ttl=60)

    tv = HybridMCPTokenVerifier(
        verifier=_make_verifier(), resolver=_make_resolver(), user_store=store, api_key_cache=cache
    )
    with patch("src.auth.mcp_token_verifiers.asyncio.to_thread", new=AsyncMock(return_value=None)):
        result = await tv.verify_token("mdbk_unknown")

    assert result is None


# ---------------------------------------------------------------------------
# UserConfigResetMiddleware
# ---------------------------------------------------------------------------


async def test_reset_middleware_resets_var_after_success():
    user = _make_user()
    reset_tok = user_config_var.set(user)  # simulate verify_token side effect
    _ucv_reset_token_var.set(reset_tok)

    mw = UserConfigResetMiddleware(_noop_app)
    scope = {"type": "http", "method": "GET", "path": "/", "headers": []}
    await mw(scope, AsyncMock(return_value={"type": "http.request", "body": b""}), AsyncMock())

    assert user_config_var.get() is None
    assert _ucv_reset_token_var.get() is None


async def test_reset_middleware_resets_var_on_exception():
    user = _make_user()
    reset_tok = user_config_var.set(user)
    _ucv_reset_token_var.set(reset_tok)

    async def _raising_app(scope, receive, send):
        raise RuntimeError("boom")

    mw = UserConfigResetMiddleware(_raising_app)
    scope = {"type": "http", "method": "GET", "path": "/", "headers": []}

    with pytest.raises(RuntimeError, match="boom"):
        await mw(scope, AsyncMock(return_value={"type": "http.request", "body": b""}), AsyncMock())

    assert user_config_var.get() is None


async def test_reset_middleware_passthrough_non_http():
    """Non-HTTP scopes (lifespan, websocket upgrade init) pass through without touching user_config_var."""
    called = []

    async def _inner(scope, receive, send):
        called.append(scope["type"])

    mw = UserConfigResetMiddleware(_inner)
    scope = {"type": "lifespan"}
    await mw(scope, AsyncMock(), AsyncMock())

    assert called == ["lifespan"]
    assert user_config_var.get() is None
