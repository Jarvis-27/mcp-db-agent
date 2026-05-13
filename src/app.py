"""Combined ASGI entry point for the hosted single-account HTTP deployment.

Hosted HTTP mode: uv run uvicorn src.app:app --workers 4 ...

MCP auth modes (controlled by MCP_AUTH_MODE setting):
  api_key_only  — bearer mdbk_* API keys only  (default)
  hybrid        — OAuth tokens preferred; API keys accepted as fallback
  oauth_only    — OAuth 2.1 access tokens only
"""

import importlib
import logging
import src.server as _server_module  # noqa: E402 — must come after sys.path setup in server.py
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any

from cachetools import TTLCache  # type: ignore[import-untyped]
from sqlalchemy import create_engine, event
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse
from starlette.routing import Mount, Route

from src.api.app import api_app
from src.auth.crypto import CredentialCipher
from src.auth.mcp_token_verifiers import (
    HybridMCPTokenVerifier,
    OAuthMCPTokenVerifier,
    UserConfigResetMiddleware,
)
from src.auth.middleware import ApiKeyMiddleware
from src.auth.rate_limiter import PerUserSlidingWindow
from src.auth.token_store import TokenStore
from src.auth.user_store import UserStore
from src.config import settings
from src.core.drain import DrainState
from src.core.heartbeat import HeartbeatMonitor
from src.core.pipeline_factory import PipelineFactory
from src.core.query_log import QueryLog
from src.email_sender import make_email_sender
from src.middleware.body_size import BodySizeLimitMiddleware
from src.middleware.drain_guard import DrainGuardMiddleware
from src.middleware.request_id import RequestIDMiddleware

log = logging.getLogger(__name__)

# Built at module-import time so the parent Starlette app can hold a stable
# reference in DrainGuardMiddleware. The lifespan shares this same instance
# with api_app.state and src.server (see below).
_drain_state = DrainState()

# CORS policy — explicit method/header lists are required when
# allow_credentials=True (CORS spec disallows wildcards in that case).
CORS_ALLOW_METHODS: list[str] = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
CORS_ALLOW_HEADERS: list[str] = [
    "Content-Type",
    "Authorization",
    "X-API-Key",
    "X-Session-Token",
    "X-Request-ID",
]
CORS_EXPOSE_HEADERS: list[str] = ["X-Request-ID"]


def _enable_sqlite_wal(engine) -> None:
    """Enable WAL mode for an SQLite engine."""

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


def _resource_metadata_url() -> str | None:
    """Return the RFC 9728 protected resource metadata URL for WWW-Authenticate headers."""
    if not settings.oauth_is_configured():
        return None
    resource_url = settings.effective_mcp_resource_url()
    try:
        from urllib.parse import urlparse

        parsed = urlparse(resource_url)
        resource_path = parsed.path if parsed.path != "/" else ""
        return (
            f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-protected-resource{resource_path}"
        )
    except Exception:
        return None


def _mounted_resource_metadata_url() -> str | None:
    """Return the protected resource metadata alias under the mounted MCP path."""
    if not settings.oauth_is_configured():
        return None
    try:
        from urllib.parse import urlparse

        parsed = urlparse(settings.effective_mcp_resource_url())
        resource_path = parsed.path.rstrip("/")
        if not resource_path:
            return None
        return (
            f"{parsed.scheme}://{parsed.netloc}{resource_path}/.well-known/oauth-protected-resource"
        )
    except Exception:
        return None


def _build_protected_resource_routes():
    """Build RFC 9728 metadata routes for the parent Starlette app.

    Returns an empty list when OAuth is not configured.
    """
    if not settings.oauth_is_configured():
        return []
    try:
        from mcp.server.auth.handlers.metadata import ProtectedResourceMetadataHandler
        from mcp.server.auth.routes import cors_middleware, create_protected_resource_routes
        from mcp.shared.auth import ProtectedResourceMetadata
        from pydantic import AnyHttpUrl
        from urllib.parse import urlparse

        resource_url = settings.effective_mcp_resource_url()
        issuer_url = settings.oauth_issuer_url.rstrip("/")
        scopes = settings.oauth_required_scopes_list() or None

        routes = create_protected_resource_routes(
            resource_url=AnyHttpUrl(resource_url),
            authorization_servers=[AnyHttpUrl(issuer_url)],
            scopes_supported=scopes,
        )

        metadata = ProtectedResourceMetadata(
            resource=AnyHttpUrl(resource_url),
            authorization_servers=[AnyHttpUrl(issuer_url)],
            scopes_supported=scopes,
        )
        handler = ProtectedResourceMetadataHandler(metadata)
        endpoint = cors_middleware(handler.handle, ["GET", "OPTIONS"])

        parsed = urlparse(resource_url)
        resource_path = parsed.path.rstrip("/")
        aliases = {"/.well-known/oauth-protected-resource"}
        if resource_path:
            aliases.add(f"{resource_path}/.well-known/oauth-protected-resource")

        existing_paths = {route.path for route in routes if hasattr(route, "path")}
        for path in sorted(aliases - existing_paths):
            routes.append(Route(path, endpoint=endpoint, methods=["GET", "OPTIONS"]))

        def redirect_to_issuer_metadata(metadata_name: str):
            async def _redirect(_request):
                return RedirectResponse(
                    f"{issuer_url}/.well-known/{metadata_name}",
                    status_code=307,
                )

            return _redirect

        if resource_path:
            for metadata_name in ("oauth-authorization-server", "openid-configuration"):
                routes.append(
                    Route(
                        f"{resource_path}/.well-known/{metadata_name}",
                        endpoint=redirect_to_issuer_metadata(metadata_name),
                        methods=["GET"],
                    )
                )

        return routes
    except Exception as exc:
        log.warning("Could not build protected resource metadata routes: %s", exc)
        return []


class MCPMountPathMiddleware:
    """Treat /mcp as the mounted MCP app root without emitting a redirect."""

    def __init__(self, app):
        self._app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] in ("http", "websocket") and scope.get("path") == "/mcp":
            scope = dict(scope)
            scope["path"] = "/mcp/"
            if scope.get("raw_path") == b"/mcp":
                scope["raw_path"] = b"/mcp/"
        await self._app(scope, receive, send)


class ResourceMetadataChallengeAliasMiddleware:
    """Rewrite auth challenges to the metadata route exposed below /mcp."""

    def __init__(self, app, *, resource_metadata_url: str | None) -> None:
        self._app = app
        self._resource_metadata_url = resource_metadata_url

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket") or not self._resource_metadata_url:
            await self._app(scope, receive, send)
            return

        async def send_with_alias(message):
            if message["type"] != "http.response.start":
                await send(message)
                return

            headers = []
            for name, value in message.get("headers", []):
                if name.lower() == b"www-authenticate":
                    text = value.decode("latin-1")
                    prefix = 'resource_metadata="'
                    start = text.find(prefix)
                    if start != -1:
                        value_start = start + len(prefix)
                        value_end = text.find('"', value_start)
                        if value_end != -1:
                            text = (
                                text[:value_start] + self._resource_metadata_url + text[value_end:]
                            )
                            value = text.encode("latin-1")
                headers.append((name, value))

            message = dict(message)
            message["headers"] = headers
            await send(message)

        await self._app(scope, receive, send_with_alias)


@asynccontextmanager
async def lifespan(app: Starlette):
    """Unified lifespan — starts all shared resources, tears them down on exit."""

    # 1. Build cipher
    keys = settings.credential_encryption_keys_list()
    if not keys:
        from cryptography.fernet import Fernet

        ephemeral = Fernet.generate_key().decode()
        log.warning(
            "CREDENTIAL_ENCRYPTION_KEYS not set — using ephemeral key. "
            "All registered users will be lost on restart. "
            "Set CREDENTIAL_ENCRYPTION_KEYS in .env for persistence."
        )
        keys = [ephemeral]
    cipher = CredentialCipher(keys)

    # 2. Build auth-DB engine
    auth_engine = create_engine(settings.auth_database_url, pool_pre_ping=True)
    if settings.auth_database_url.startswith("sqlite"):
        _enable_sqlite_wal(auth_engine)

    # 3. Run migrations in development; refuse to start in production if behind
    if settings.environment == "development":
        try:
            from alembic import command
            from alembic.config import Config

            from pathlib import Path

            alembic_cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
            alembic_cfg.set_main_option(
                "script_location", str(Path(__file__).parent.parent / "alembic")
            )
            alembic_cfg.set_main_option("sqlalchemy.url", settings.auth_database_url)
            command.upgrade(alembic_cfg, "head")
        except Exception as exc:
            log.warning("Alembic auto-migration failed (dev mode): %s", exc)
            from src.auth.user_store import Base

            Base.metadata.create_all(auth_engine)
    else:
        try:
            from pathlib import Path as _Path
            from alembic.config import Config as _AlembicConfig
            from alembic.runtime.migration import MigrationContext
            from alembic.script import ScriptDirectory

            _alembic_cfg = _AlembicConfig(str(_Path(__file__).parent.parent / "alembic.ini"))
            _alembic_cfg.set_main_option(
                "script_location", str(_Path(__file__).parent.parent / "alembic")
            )
            _script_dir = ScriptDirectory.from_config(_alembic_cfg)
            expected_head = _script_dir.get_current_head()

            with auth_engine.connect() as conn:
                ctx = MigrationContext.configure(conn)
                current = ctx.get_current_revision()
            if current != expected_head:
                log.error(
                    "Alembic schema is not at head (current=%s, expected=%s). "
                    "Run `alembic upgrade head` before starting production.",
                    current,
                    expected_head,
                )
                raise RuntimeError("Database schema is not up to date")
        except Exception as exc:
            if "schema is not up to date" in str(exc):
                raise
            log.warning("Could not verify Alembic schema version: %s", exc)

    # 4. Build UserStore, caches, executor pool, query log, pipeline factory
    user_store = UserStore(auth_engine, cipher)
    auth_key_cache: TTLCache = TTLCache(maxsize=10_000, ttl=60)
    user_session_cache: TTLCache = TTLCache(maxsize=10_000, ttl=60)
    executor_pool = ThreadPoolExecutor(
        max_workers=settings.query_pool_size, thread_name_prefix="sql-exec"
    )
    query_log = QueryLog(engine=auth_engine)
    factory = PipelineFactory(settings, executor_pool)

    # 5. Build TokenStore and EmailSender
    token_store = TokenStore(
        engine=auth_engine,
        email_token_ttl_minutes=settings.email_verification_token_ttl_minutes,
        login_token_ttl_minutes=settings.login_link_token_ttl_minutes,
    )
    email_sender = make_email_sender(settings)

    # 6. Stash on api_app.state for FastAPI dependency injection
    heartbeat = HeartbeatMonitor()
    heartbeat.start()

    api_app.state.user_store = user_store
    api_app.state.auth_key_cache = auth_key_cache
    api_app.state.user_session_cache = user_session_cache
    api_app.state.factory = factory
    api_app.state.executor_pool = executor_pool
    api_app.state.token_store = token_store
    api_app.state.email_sender = email_sender
    api_app.state.cipher = cipher
    api_app.state.query_log = query_log
    api_app.state.heartbeat = heartbeat
    api_app.state.drain_state = _drain_state

    # Also stash on the parent Starlette app's state
    app.state.user_store = user_store
    app.state.auth_key_cache = auth_key_cache
    app.state.heartbeat = heartbeat
    app.state.drain_state = _drain_state

    # 7. Stash factory, query_log, user_store, and MCP burst limiter on server module
    server_module = importlib.import_module("src.server")
    server_module._factory = factory  # type: ignore[attr-defined]
    server_module._query_log = query_log  # type: ignore[attr-defined]
    server_module._user_store = user_store  # type: ignore[attr-defined]
    server_module._drain_state = _drain_state  # type: ignore[attr-defined]
    server_module._mcp_limiter = PerUserSlidingWindow(  # type: ignore[attr-defined]
        capacity=settings.mcp_burst_capacity,
        window_seconds=settings.mcp_burst_window_seconds,
    )

    # 8. Build the auth-wired MCP ASGI app now that UserStore is available
    mcp_mount_index = _find_mcp_mount_index(app)
    if mcp_mount_index is not None:
        auth_mode = settings.mcp_auth_mode
        mcp_asgi = _build_mcp_asgi(
            auth_mode=auth_mode,
            user_store=user_store,
            api_key_cache=auth_key_cache,
        )
        app.routes[mcp_mount_index] = Mount("/mcp", app=mcp_asgi)
        log.info("MCP auth mode: %s", auth_mode)

    log.info("MCP Database Analytics Agent started (hosted single-account HTTP mode)")

    async with _server_module.mcp.session_manager.run():
        try:
            yield
        finally:
            log.info("Shutting down...")
            _drain_state.begin_drain()
            remaining = await _drain_state.wait_for_in_flight(
                settings.shutdown_grace_period_seconds
            )
            if remaining:
                log.warning(
                    "drain_grace_expired_cancelling_in_flight",
                    extra={"in_flight": remaining},
                )
                await _drain_state.cancel_remaining(settle_seconds=2.0)
            await heartbeat.stop()
            await factory.shutdown()
            # cancel_futures only cancels queued (not-yet-started) futures;
            # in-flight SQL keeps running on its thread until the DB-side
            # statement_timeout / SQLite interrupt() from G8 kills it.
            executor_pool.shutdown(wait=False, cancel_futures=True)
            auth_engine.dispose()


# ---------------------------------------------------------------------------
# MCP auth wrapper construction
# ---------------------------------------------------------------------------


def _find_mcp_mount_index(app: Starlette) -> int | None:
    for i, route in enumerate(app.routes):
        if isinstance(route, Mount) and route.path == "/mcp":
            return i
    return None


def _build_mcp_asgi(*, auth_mode: str, user_store: UserStore, api_key_cache: TTLCache):
    """Build the auth-wired MCP ASGI app for the given auth mode.

    For ``api_key_only`` (or OAuth modes where OAuth is not yet configured),
    the existing ``ApiKeyLazyWrapper`` path is used unchanged.

    For ``oauth_only`` and ``hybrid``, we inject a ``TokenVerifier`` adapter
    and ``AuthSettings`` into the FastMCP instance before calling
    ``streamable_http_app()``.  FastMCP then handles ``BearerAuthBackend``,
    ``RequireAuthMiddleware``, and ``WWW-Authenticate`` challenge responses
    natively.  A thin ``UserConfigResetMiddleware`` wrapper resets
    ``user_config_var`` after each request.

    Note: ``streamable_http_app()`` is deferred to this function (called in
    the lifespan) so that the ``UserStore`` is available when building the
    token verifier.  Calling this function twice on the same ``mcp`` instance
    is safe — the session manager is reused on the second call.
    """
    mcp = _server_module.mcp
    raw_app: Any

    if auth_mode == "api_key_only" or not settings.oauth_is_configured():
        if auth_mode != "api_key_only":
            log.warning(
                "MCP_AUTH_MODE=%s but OAuth is not configured "
                "(OAUTH_ISSUER_URL and MCP_RESOURCE_URL are required). "
                "Falling back to api_key_only.",
                auth_mode,
            )
        raw_app = mcp.streamable_http_app()
        return _api_key_wrapper(raw_app, user_store, api_key_cache)

    verifier, resolver = _make_oauth_components(user_store)

    token_verifier: OAuthMCPTokenVerifier | HybridMCPTokenVerifier
    if auth_mode == "oauth_only":
        token_verifier = OAuthMCPTokenVerifier(verifier=verifier, resolver=resolver)
    else:  # hybrid
        token_verifier = HybridMCPTokenVerifier(
            verifier=verifier,
            resolver=resolver,
            user_store=user_store,
            api_key_cache=api_key_cache,
            fastmcp_required_scopes=settings.oauth_required_scopes_list(),
        )

    from mcp.server.auth.settings import AuthSettings
    from pydantic import AnyHttpUrl

    mcp.settings.auth = AuthSettings(
        issuer_url=AnyHttpUrl(settings.oauth_issuer_url.rstrip("/")),
        required_scopes=settings.oauth_required_scopes_list() or None,
        resource_server_url=AnyHttpUrl(settings.effective_mcp_resource_url()),
    )
    mcp._token_verifier = token_verifier

    raw_app = mcp.streamable_http_app()
    raw_app = ResourceMetadataChallengeAliasMiddleware(
        raw_app,
        resource_metadata_url=_mounted_resource_metadata_url(),
    )
    return UserConfigResetMiddleware(raw_app)


def _api_key_wrapper(mcp_app, user_store: UserStore, cache: TTLCache) -> "ApiKeyLazyWrapper":
    return ApiKeyLazyWrapper(mcp_app, user_store=user_store, cache=cache)


def _make_oauth_components(user_store: UserStore):
    from src.auth.oauth_verifier import OAuthVerifier
    from src.auth.oauth_identity import OAuthIdentityResolver

    verifier = OAuthVerifier(
        issuer_url=settings.oauth_issuer_url,
        audience=settings.oauth_audience,
        required_scopes=settings.oauth_required_scopes_list(),
        jwks_url=settings.oauth_jwks_url,
        jwks_cache_ttl=settings.oauth_jwks_cache_seconds,
    )
    resolver = OAuthIdentityResolver(user_store)
    return verifier, resolver


# ---------------------------------------------------------------------------
# Lazy API-key wrapper (preserves previous lifespan-safe pattern)
# ---------------------------------------------------------------------------


class ApiKeyLazyWrapper:
    """Wraps the MCP ASGI app with ApiKeyMiddleware after startup."""

    def __init__(self, inner_app, *, user_store: UserStore, cache: TTLCache) -> None:
        self._inner = inner_app
        self._mw = ApiKeyMiddleware(inner_app, user_store=user_store, cache=cache)

    async def __call__(self, scope, receive, send):
        await self._mw(scope, receive, send)


# ---------------------------------------------------------------------------
# Build routes (including protected resource metadata if OAuth is configured)
# ---------------------------------------------------------------------------


# The /mcp mount uses a startup placeholder because streamable_http_app() must
# be called in the lifespan (after UserStore is available for token verifiers).
# The lifespan replaces this mount before any requests are served.
async def _mcp_startup_placeholder(scope, receive, send) -> None:
    """503 stub — replaced in lifespan before the first request is served."""
    if scope["type"] == "http":
        await send({"type": "http.response.start", "status": 503, "headers": []})
        await send({"type": "http.response.body", "body": b'{"detail":"server starting"}'})


_protected_resource_routes = _build_protected_resource_routes()
_base_routes = [
    Mount("/api", app=api_app),
    *_protected_resource_routes,
    Mount("/mcp", app=_mcp_startup_placeholder),  # replaced in lifespan
]

# ---------------------------------------------------------------------------
# Parent Starlette app — lifespan lives HERE, not on sub-apps
# ---------------------------------------------------------------------------

app = Starlette(
    lifespan=lifespan,
    routes=_base_routes,
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_credentials=True,
            allow_methods=CORS_ALLOW_METHODS,
            allow_headers=CORS_ALLOW_HEADERS,
            expose_headers=CORS_EXPOSE_HEADERS,
        ),
        Middleware(MCPMountPathMiddleware),
        Middleware(RequestIDMiddleware),
        Middleware(DrainGuardMiddleware, drain_state=_drain_state),
        Middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes),
    ],
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.app:app",
        host="0.0.0.0",
        port=settings.port,
        proxy_headers=True,
        forwarded_allow_ips=settings.trusted_proxy_ips or "127.0.0.1",
    )
