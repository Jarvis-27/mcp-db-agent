"""FastMCP TokenVerifier adapters for the /mcp OAuth resource-server path.

These classes implement the ``TokenVerifier`` protocol expected by FastMCP's
native auth layer (``mcp.server.auth.provider.TokenVerifier``).  They bridge
our existing ``OAuthVerifier`` / ``OAuthIdentityResolver`` / ``UserStore``
plumbing to the ``async verify_token(token) -> AccessToken | None`` interface.

All synchronous I/O (JWKS fetch, DB lookup) is dispatched to a thread via
``asyncio.to_thread`` so the event loop is never blocked.

As a side effect, every successful ``verify_token`` call sets ``user_config_var``
(the ContextVar read by tool code in ``src/tools/``) for the duration of the
current asyncio Task.  ``UserConfigResetMiddleware`` resets it in a ``finally``
block after the response is sent.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from contextvars import ContextVar
from typing import Any

from cachetools import TTLCache  # type: ignore[import-untyped]
from mcp.server.auth.provider import AccessToken

from src.auth.middleware import user_config_var
from src.auth.oauth_identity import OAuthIdentityError, OAuthIdentityResolver
from src.auth.oauth_verifier import OAuthVerificationError, OAuthVerifier
from src.auth.user_store import UserStore

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal reset-token tracker
# ---------------------------------------------------------------------------

# Stores the Token object returned by user_config_var.set(...) so that
# UserConfigResetMiddleware can call user_config_var.reset(token) at the end
# of the request, restoring the ContextVar to its pre-request state.
_ucv_reset_token_var: ContextVar[Any] = ContextVar("_ucv_reset_token", default=None)


def _store_user_config(user_config) -> None:
    """Set user_config_var and record the reset token for later cleanup."""
    reset_token = user_config_var.set(user_config)
    _ucv_reset_token_var.set(reset_token)


# ---------------------------------------------------------------------------
# OAuth-only verifier
# ---------------------------------------------------------------------------


class OAuthMCPTokenVerifier:
    """FastMCP TokenVerifier for ``oauth_only`` mode.

    Validates a bearer JWT via ``OAuthVerifier``, resolves it to a local
    account via ``OAuthIdentityResolver``, and returns an ``AccessToken``.
    Returns ``None`` on any failure (FastMCP converts this to a 401 response).
    """

    def __init__(
        self,
        verifier: OAuthVerifier,
        resolver: OAuthIdentityResolver,
    ) -> None:
        self._verifier = verifier
        self._resolver = resolver

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = await asyncio.to_thread(self._verifier.verify, token)
        except OAuthVerificationError as exc:
            log.info("OAuth token verification failed: %s", exc)
            return None
        except Exception as exc:
            log.warning("Unexpected error during OAuth token verification: %s", exc)
            return None

        try:
            user_config = await asyncio.to_thread(self._resolver.resolve, claims)
        except OAuthIdentityError as exc:
            log.info("OAuth identity resolution failed (code=%s): %s", exc.code, exc)
            return None
        except Exception as exc:
            log.warning("Unexpected error during OAuth identity resolution: %s", exc)
            return None

        _store_user_config(user_config)
        return AccessToken(
            token=token,
            client_id=user_config.user_id,
            scopes=list(claims.scopes),
            expires_at=claims.expires_at,
        )


# ---------------------------------------------------------------------------
# Hybrid verifier (OAuth preferred; API keys as fallback)
# ---------------------------------------------------------------------------

_API_KEY_PREFIX = "mdbk_"


class HybridMCPTokenVerifier:
    """FastMCP TokenVerifier for ``hybrid`` mode.

    Tokens starting with ``mdbk_`` are resolved through the API-key path
    (DB lookup with a TTL cache).  All other bearer values are treated as
    OAuth JWTs and delegated to ``OAuthMCPTokenVerifier``.
    """

    def __init__(
        self,
        verifier: OAuthVerifier,
        resolver: OAuthIdentityResolver,
        user_store: UserStore,
        api_key_cache: TTLCache,
        fastmcp_required_scopes: list[str] | None = None,
    ) -> None:
        self._oauth = OAuthMCPTokenVerifier(verifier=verifier, resolver=resolver)
        self._user_store = user_store
        self._cache = api_key_cache
        self._fastmcp_required_scopes = tuple(fastmcp_required_scopes or [])

    async def verify_token(self, token: str) -> AccessToken | None:
        if token.startswith(_API_KEY_PREFIX):
            return await self._resolve_api_key(token)
        return await self._oauth.verify_token(token)

    async def _resolve_api_key(self, raw_key: str) -> AccessToken | None:
        cache_key = hashlib.sha256(raw_key.encode()).hexdigest()
        user_config = self._cache.get(cache_key)

        if user_config is None:
            user_config = await asyncio.to_thread(
                self._user_store.get_user_by_api_key, raw_key
            )
            if user_config is None:
                log.info("Hybrid: API key not found or inactive")
                return None
            if "mcp_read" not in user_config.scopes:
                log.info("Hybrid: API key lacks mcp_read scope")
                return None
            self._cache[cache_key] = user_config

        _store_user_config(user_config)
        return AccessToken(
            token=raw_key,
            client_id=user_config.user_id,
            scopes=list(dict.fromkeys([*user_config.scopes, *self._fastmcp_required_scopes])),
        )


# ---------------------------------------------------------------------------
# UserConfigResetMiddleware
# ---------------------------------------------------------------------------


class UserConfigResetMiddleware:
    """Thin ASGI wrapper that resets ``user_config_var`` after each request.

    Must be the outermost wrapper around the ASGI app returned by
    ``FastMCP.streamable_http_app()``.  The ``verify_token`` call that sets
    ``user_config_var`` happens inside FastMCP's auth pipeline, which runs
    before the MCP handler — so the reset here fires after the full response
    is sent.
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        try:
            await self._app(scope, receive, send)
        finally:
            reset_token = _ucv_reset_token_var.get()
            if reset_token is not None:
                user_config_var.reset(reset_token)
            _ucv_reset_token_var.set(None)
