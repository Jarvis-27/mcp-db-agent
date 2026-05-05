"""Unit tests for OAuthMCPMiddleware and HybridMCPMiddleware."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from cachetools import TTLCache

from src.auth.middleware import HybridMCPMiddleware, OAuthMCPMiddleware, user_config_var
from src.auth.oauth_identity import OAuthIdentityError
from src.auth.oauth_verifier import OAuthClaims, OAuthVerificationError
from src.auth.user_store import UserConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(user_id: str = "u-1") -> UserConfig:
    return UserConfig(
        user_id=user_id,
        database_url="sqlite:///./demo.db",
        is_active=True,
        onboarding_status="setup_complete",
        email="test@example.com",
    )


def _make_claims() -> OAuthClaims:
    return OAuthClaims(
        issuer="https://auth.example.com",
        subject="oauth2|user123",
        scopes=frozenset({"mcp:access"}),
        expires_at=int(time.time()) + 3600,
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
    """Run *middleware* and capture the ASGI response."""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp/",
        "headers": headers,
    }
    received = []

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


# ---------------------------------------------------------------------------
# OAuthMCPMiddleware — happy path
# ---------------------------------------------------------------------------


async def test_oauth_middleware_accepts_valid_token():
    user = _make_user()
    mw = OAuthMCPMiddleware(
        _noop_app,
        verifier=_make_verifier(),
        resolver=_make_resolver(user=user),
    )
    status, _, _ = await _run(mw, [(b"authorization", b"Bearer some.jwt.token")])
    assert status == 200


async def test_oauth_middleware_sets_user_config_var():
    user = _make_user()
    seen = []

    async def capturing_app(scope, receive, send):
        seen.append(user_config_var.get())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = OAuthMCPMiddleware(
        capturing_app,
        verifier=_make_verifier(),
        resolver=_make_resolver(user=user),
    )
    await _run(mw, [(b"authorization", b"Bearer valid.token")])
    assert seen == [user]


async def test_oauth_middleware_resets_user_config_var_after_request():
    mw = OAuthMCPMiddleware(
        _noop_app,
        verifier=_make_verifier(),
        resolver=_make_resolver(),
    )
    await _run(mw, [(b"authorization", b"Bearer valid.token")])
    assert user_config_var.get() is None


# ---------------------------------------------------------------------------
# OAuthMCPMiddleware — rejection cases
# ---------------------------------------------------------------------------


async def test_oauth_middleware_missing_token_returns_401():
    mw = OAuthMCPMiddleware(
        _noop_app,
        verifier=_make_verifier(),
        resolver=_make_resolver(),
    )
    status, body, headers = await _run(mw, [])
    assert status == 401
    assert b"www-authenticate" in bytes(str(headers).lower(), "utf-8") or "www-authenticate" in {
        k.lower() for k in headers
    }


async def test_oauth_middleware_invalid_token_returns_401():
    mw = OAuthMCPMiddleware(
        _noop_app,
        verifier=_make_verifier(raises=OAuthVerificationError("Token has expired")),
        resolver=_make_resolver(),
    )
    status, body, _ = await _run(mw, [(b"authorization", b"Bearer bad.token")])
    assert status == 401
    assert b"expired" in body


async def test_oauth_middleware_no_linked_account_returns_401():
    mw = OAuthMCPMiddleware(
        _noop_app,
        verifier=_make_verifier(),
        resolver=_make_resolver(
            raises=OAuthIdentityError("No linked account", code="no_linked_account")
        ),
    )
    status, body, _ = await _run(mw, [(b"authorization", b"Bearer valid.token")])
    assert status == 401
    assert b"No linked account" in body


async def test_oauth_middleware_includes_resource_metadata_in_www_authenticate():
    meta_url = "https://api.example.com/.well-known/oauth-protected-resource/mcp"
    mw = OAuthMCPMiddleware(
        _noop_app,
        verifier=_make_verifier(raises=OAuthVerificationError("bad token")),
        resolver=_make_resolver(),
        resource_metadata_url=meta_url,
    )
    _, _, headers = await _run(mw, [(b"authorization", b"Bearer x")])
    www_auth = headers.get("www-authenticate", "")
    assert meta_url in www_auth


# ---------------------------------------------------------------------------
# OAuthMCPMiddleware — lifespan pass-through
# ---------------------------------------------------------------------------


async def test_oauth_middleware_passes_non_http_scopes():
    passed = []

    async def inner(scope, receive, send):
        passed.append(scope["type"])

    mw = OAuthMCPMiddleware(inner, verifier=_make_verifier(), resolver=_make_resolver())
    await mw({"type": "lifespan"}, None, None)
    assert passed == ["lifespan"]


# ---------------------------------------------------------------------------
# HybridMCPMiddleware — API key path
# ---------------------------------------------------------------------------


async def test_hybrid_routes_api_key_correctly():
    user = _make_user()
    cache = TTLCache(maxsize=100, ttl=60)
    store = _make_store(user=user)
    store.get_user_by_api_key.return_value = user

    # Patch scopes
    user_with_scope = UserConfig(
        user_id="u-1",
        database_url="sqlite:///./demo.db",
        is_active=True,
        onboarding_status="setup_complete",
        email=None,
        scopes=frozenset({"mcp_read"}),
    )
    store.get_user_by_api_key.return_value = user_with_scope

    seen = []

    async def capturing_app(scope, receive, send):
        seen.append(user_config_var.get())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = HybridMCPMiddleware(
        capturing_app,
        verifier=_make_verifier(),
        resolver=_make_resolver(),
        user_store=store,
        api_key_cache=cache,
    )
    await _run(mw, [(b"authorization", b"Bearer mdbk_test_key")])
    assert seen == [user_with_scope]
    # OAuth verifier should NOT have been called
    mw._verifier.verify.assert_not_called()  # type: ignore[attr-defined]


async def test_hybrid_routes_oauth_token_correctly():
    user = _make_user()
    cache = TTLCache(maxsize=100, ttl=60)
    store = _make_store()

    seen = []

    async def capturing_app(scope, receive, send):
        seen.append(user_config_var.get())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = HybridMCPMiddleware(
        capturing_app,
        verifier=_make_verifier(),
        resolver=_make_resolver(user=user),
        user_store=store,
        api_key_cache=cache,
    )
    # Token does NOT start with mdbk_ → goes through OAuth path
    await _run(mw, [(b"authorization", b"Bearer some.jwt.token")])
    assert seen == [user]
    store.get_user_by_api_key.assert_not_called()


async def test_hybrid_returns_401_when_neither_path_succeeds():
    cache = TTLCache(maxsize=100, ttl=60)
    store = _make_store(user=None)

    mw = HybridMCPMiddleware(
        _noop_app,
        verifier=_make_verifier(raises=OAuthVerificationError("bad token")),
        resolver=_make_resolver(),
        user_store=store,
        api_key_cache=cache,
    )
    status, body, _ = await _run(mw, [(b"authorization", b"Bearer some.jwt")])
    assert status == 401


async def test_hybrid_missing_token_returns_401():
    cache = TTLCache(maxsize=100, ttl=60)
    store = _make_store()

    mw = HybridMCPMiddleware(
        _noop_app,
        verifier=_make_verifier(),
        resolver=_make_resolver(),
        user_store=store,
        api_key_cache=cache,
    )
    status, _, _ = await _run(mw, [])
    assert status == 401
