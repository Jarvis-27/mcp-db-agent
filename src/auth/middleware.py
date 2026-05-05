"""ASGI middleware for MCP endpoint authentication and per-request user scoping.

Three concrete middleware classes cover the three auth modes:

- :class:`ApiKeyMiddleware` — ``api_key_only`` (original behaviour)
- :class:`OAuthMCPMiddleware` — ``oauth_only``
- :class:`HybridMCPMiddleware` — ``hybrid`` (OAuth preferred; API keys accepted as fallback)

All three set :data:`user_config_var` for the duration of the request and reset
it in a ``finally`` block.  Tool code in ``server.py`` reads this ContextVar.
"""

from __future__ import annotations

import hashlib
import json
import logging
from contextvars import ContextVar
from typing import Callable

from cachetools import TTLCache  # type: ignore[import-untyped]

from src.auth.user_store import UserConfig, UserStore

log = logging.getLogger(__name__)

# ContextVar set per-request by all middleware classes; reset in finally.
# Tools in server.py read this to get the current user's configuration.
user_config_var: ContextVar[UserConfig | None] = ContextVar("user_config", default=None)

# Prefix that identifies mdbk_* API keys (as opposed to OAuth JWTs).
_API_KEY_PREFIX = "mdbk_"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _extract_bearer(headers: list[tuple[bytes, bytes]]) -> str | None:
    """Return the raw bearer value from X-API-Key or Authorization: Bearer headers."""
    for name, value in headers:
        name_lower = name.lower()
        if name_lower == b"x-api-key":
            return value.decode("utf-8", errors="replace").strip()
        if name_lower == b"authorization":
            val = value.decode("utf-8", errors="replace").strip()
            if val.lower().startswith("bearer "):
                return val[7:].strip()
    return None


async def _send_json(
    send: Callable, *, status: int, body: dict, extra_headers: list | None = None
) -> None:
    encoded = json.dumps(body).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(encoded)).encode()),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": encoded})


def _www_authenticate_header(resource_metadata_url: str | None = None) -> bytes:
    """Build a standards-compliant WWW-Authenticate header value for Bearer auth."""
    parts = ['error="invalid_token"', 'error_description="Authentication required"']
    if resource_metadata_url:
        parts.append(f'resource_metadata="{resource_metadata_url}"')
    return f"Bearer {', '.join(parts)}".encode()


# ---------------------------------------------------------------------------
# API-key-only middleware (original behaviour)
# ---------------------------------------------------------------------------


class ApiKeyMiddleware:
    """ASGI middleware that authenticates via mdbk_* API keys only.

    - Reads the key from X-API-Key or Authorization: Bearer headers.
    - Caches lookups (keyed on sha256(key), never the raw key) for 60 s.
    - Sets user_config_var for the duration of the request.
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

        raw_key = _extract_bearer(scope.get("headers", []))
        if raw_key is None:
            await _send_json(send, status=401, body={"detail": "Missing API key"})
            return

        cache_key = hashlib.sha256(raw_key.encode()).hexdigest()
        user_config: UserConfig | None = self._cache.get(cache_key)
        if user_config is None:
            user_config = self._user_store.get_user_by_api_key(raw_key)
            if user_config is None:
                await _send_json(send, status=401, body={"detail": "Invalid or inactive API key"})
                return
            if "mcp_read" not in user_config.scopes:
                await _send_json(
                    send, status=401, body={"detail": "API key is not permitted for MCP access"}
                )
                return
            self._cache[cache_key] = user_config

        token = user_config_var.set(user_config)
        try:
            await self._app(scope, receive, send)
        finally:
            user_config_var.reset(token)


# ---------------------------------------------------------------------------
# OAuth-only middleware (DEPRECATED)
# ---------------------------------------------------------------------------


# DEPRECATED: Use src.auth.mcp_token_verifiers.OAuthMCPTokenVerifier with FastMCP
# native auth (token_verifier + AuthSettings) instead.  This class is retained
# only so that tests/auth/test_oauth_middleware.py continues to pass during the
# transition.  It will be deleted once test_mcp_token_verifiers.py is confirmed.
class OAuthMCPMiddleware:
    """ASGI middleware that enforces OAuth 2.1 bearer tokens at /mcp.

    Tokens are validated using :class:`~src.auth.oauth_verifier.OAuthVerifier`
    and resolved to a local account via
    :class:`~src.auth.oauth_identity.OAuthIdentityResolver`.

    On 401, the response includes a ``WWW-Authenticate`` header with the
    protected resource metadata URL so OAuth clients can discover auth details.
    """

    def __init__(
        self,
        app,
        *,
        verifier,  # OAuthVerifier
        resolver,  # OAuthIdentityResolver
        resource_metadata_url: str | None = None,
    ) -> None:
        self._app = app
        self._verifier = verifier
        self._resolver = resolver
        self._resource_metadata_url = resource_metadata_url

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        raw_token = _extract_bearer(scope.get("headers", []))
        if raw_token is None:
            await self._reject(send, "Authentication required — provide an OAuth bearer token")
            return

        user_config = await self._resolve(raw_token, send)
        if user_config is None:
            return  # response already sent

        token = user_config_var.set(user_config)
        try:
            await self._app(scope, receive, send)
        finally:
            user_config_var.reset(token)

    async def _resolve(self, raw_token: str, send) -> UserConfig | None:
        from src.auth.oauth_verifier import OAuthVerificationError
        from src.auth.oauth_identity import OAuthIdentityError

        try:
            claims = self._verifier.verify(raw_token)
        except OAuthVerificationError as exc:
            log.info("OAuth token verification failed: %s", exc)
            await self._reject(send, str(exc))
            return None

        try:
            return self._resolver.resolve(claims)
        except OAuthIdentityError as exc:
            log.info("OAuth identity resolution failed (code=%s): %s", exc.code, exc)
            await self._reject(send, str(exc))
            return None

    async def _reject(self, send, message: str) -> None:
        www_auth = _www_authenticate_header(self._resource_metadata_url)
        await _send_json(
            send,
            status=401,
            body={"detail": message},
            extra_headers=[(b"www-authenticate", www_auth)],
        )


# ---------------------------------------------------------------------------
# Hybrid middleware (OAuth preferred, API keys as fallback) (DEPRECATED)
# ---------------------------------------------------------------------------


# DEPRECATED: Use src.auth.mcp_token_verifiers.HybridMCPTokenVerifier with FastMCP
# native auth instead.  Retained for test continuity during transition.
class HybridMCPMiddleware:
    """ASGI middleware that accepts both OAuth tokens and mdbk_* API keys.

    Tokens that start with ``mdbk_`` are routed through the API-key path.
    All other bearer values are treated as OAuth access tokens.

    This is the recommended posture during a rollout from api_key_only to
    oauth_only.
    """

    def __init__(
        self,
        app,
        *,
        verifier,  # OAuthVerifier
        resolver,  # OAuthIdentityResolver
        user_store: UserStore,
        api_key_cache: TTLCache,
        resource_metadata_url: str | None = None,
    ) -> None:
        self._app = app
        self._verifier = verifier
        self._resolver = resolver
        self._user_store = user_store
        self._api_key_cache = api_key_cache
        self._resource_metadata_url = resource_metadata_url

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        raw_token = _extract_bearer(scope.get("headers", []))
        if raw_token is None:
            await self._reject_401(send, "Authentication required")
            return

        if raw_token.startswith(_API_KEY_PREFIX):
            user_config = self._resolve_api_key(raw_token)
        else:
            user_config = await self._resolve_oauth(raw_token, send)
            if user_config is None:
                return  # response already sent

        if user_config is None:
            await self._reject_401(send, "Invalid or inactive credentials")
            return

        token = user_config_var.set(user_config)
        try:
            await self._app(scope, receive, send)
        finally:
            user_config_var.reset(token)

    def _resolve_api_key(self, raw_key: str) -> UserConfig | None:
        cache_key = hashlib.sha256(raw_key.encode()).hexdigest()
        cached: UserConfig | None = self._api_key_cache.get(cache_key)
        if cached is not None:
            return cached
        user_config = self._user_store.get_user_by_api_key(raw_key)
        if user_config is None:
            return None
        if "mcp_read" not in user_config.scopes:
            return None
        self._api_key_cache[cache_key] = user_config
        return user_config

    async def _resolve_oauth(self, raw_token: str, send) -> UserConfig | None:
        from src.auth.oauth_verifier import OAuthVerificationError
        from src.auth.oauth_identity import OAuthIdentityError

        try:
            claims = self._verifier.verify(raw_token)
        except OAuthVerificationError as exc:
            log.info("Hybrid: OAuth token verification failed: %s", exc)
            await self._reject_401(send, str(exc))
            return None

        try:
            return self._resolver.resolve(claims)
        except OAuthIdentityError as exc:
            log.info("Hybrid: OAuth identity resolution failed (code=%s): %s", exc.code, exc)
            await self._reject_401(send, str(exc))
            return None

    async def _reject_401(self, send, message: str) -> None:
        www_auth = _www_authenticate_header(self._resource_metadata_url)
        await _send_json(
            send,
            status=401,
            body={"detail": message},
            extra_headers=[(b"www-authenticate", www_auth)],
        )
