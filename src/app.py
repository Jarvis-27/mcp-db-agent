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

from cachetools import TTLCache  # type: ignore[import-untyped]
from sqlalchemy import create_engine, event
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Mount

from src.api.app import api_app
from src.auth.crypto import CredentialCipher
from src.auth.middleware import ApiKeyMiddleware, HybridMCPMiddleware, OAuthMCPMiddleware
from src.auth.token_store import TokenStore
from src.auth.user_store import UserStore
from src.config import settings
from src.core.pipeline_factory import PipelineFactory
from src.core.query_log import QueryLog
from src.email_sender import make_email_sender
from src.middleware.body_size import BodySizeLimitMiddleware
from src.middleware.request_id import RequestIDMiddleware

log = logging.getLogger(__name__)


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
        return f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-protected-resource{resource_path}"
    except Exception:
        return None


def _build_protected_resource_routes():
    """Build RFC 9728 metadata routes for the parent Starlette app.

    Returns an empty list when OAuth is not configured.
    """
    if not settings.oauth_is_configured():
        return []
    try:
        from mcp.server.auth.routes import create_protected_resource_routes
        from pydantic import AnyHttpUrl

        resource_url = settings.effective_mcp_resource_url()
        issuer_url = settings.oauth_issuer_url.rstrip("/")
        scopes = settings.oauth_required_scopes_list() or None
        return create_protected_resource_routes(
            resource_url=AnyHttpUrl(resource_url),
            authorization_servers=[AnyHttpUrl(issuer_url)],
            scopes_supported=scopes,
        )
    except Exception as exc:
        log.warning("Could not build protected resource metadata routes: %s", exc)
        return []


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
    api_app.state.user_store = user_store
    api_app.state.auth_key_cache = auth_key_cache
    api_app.state.user_session_cache = user_session_cache
    api_app.state.factory = factory
    api_app.state.token_store = token_store
    api_app.state.email_sender = email_sender
    api_app.state.cipher = cipher
    api_app.state.query_log = query_log

    # Also stash on the parent Starlette app's state
    app.state.user_store = user_store
    app.state.auth_key_cache = auth_key_cache

    # 7. Stash factory, query_log, and user_store on server module for MCP tool handlers
    server_module = importlib.import_module("src.server")
    server_module._factory = factory  # type: ignore[attr-defined]
    server_module._query_log = query_log  # type: ignore[attr-defined]
    server_module._user_store = user_store  # type: ignore[attr-defined]

    # 8. Wire MCP auth middleware now that UserStore is available
    mcp_mount_index = _find_mcp_mount_index(app)
    if mcp_mount_index is not None:
        auth_mode = settings.mcp_auth_mode
        wrapped = _wrap_mcp_app(
            _mcp_app,
            auth_mode=auth_mode,
            user_store=user_store,
            api_key_cache=auth_key_cache,
        )
        app.routes[mcp_mount_index] = Mount("/mcp", app=wrapped)
        log.info("MCP auth mode: %s", auth_mode)

    log.info("MCP Database Analytics Agent started (hosted single-account HTTP mode)")

    async with _server_module.mcp.session_manager.run():
        try:
            yield
        finally:
            log.info("Shutting down...")
            await factory.shutdown()
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


def _wrap_mcp_app(mcp_app, *, auth_mode: str, user_store: UserStore, api_key_cache: TTLCache):
    """Return the appropriate auth-wrapping ASGI app for *mcp_app*."""
    meta_url = _resource_metadata_url()

    if auth_mode == "oauth_only":
        if not settings.oauth_is_configured():
            log.error(
                "MCP_AUTH_MODE=oauth_only but OAuth is not configured "
                "(OAUTH_ISSUER_URL and MCP_RESOURCE_URL are required). "
                "Falling back to api_key_only."
            )
            return _api_key_wrapper(mcp_app, user_store, api_key_cache)
        verifier, resolver = _make_oauth_components(user_store)
        return OAuthMCPMiddleware(
            mcp_app,
            verifier=verifier,
            resolver=resolver,
            resource_metadata_url=meta_url,
        )

    if auth_mode == "hybrid":
        if not settings.oauth_is_configured():
            log.warning(
                "MCP_AUTH_MODE=hybrid but OAuth is not configured — using api_key_only."
            )
            return _api_key_wrapper(mcp_app, user_store, api_key_cache)
        verifier, resolver = _make_oauth_components(user_store)
        return HybridMCPMiddleware(
            mcp_app,
            verifier=verifier,
            resolver=resolver,
            user_store=user_store,
            api_key_cache=api_key_cache,
            resource_metadata_url=meta_url,
        )

    # Default: api_key_only
    return _api_key_wrapper(mcp_app, user_store, api_key_cache)


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
# Build the MCP ASGI app
# ---------------------------------------------------------------------------

_mcp_app = _server_module.mcp.streamable_http_app()

# ---------------------------------------------------------------------------
# Build routes (including protected resource metadata if OAuth is configured)
# ---------------------------------------------------------------------------

_base_routes = [
    Mount("/api", app=api_app),
    Mount("/mcp", app=_mcp_app),  # placeholder; replaced in lifespan
]
_base_routes.extend(_build_protected_resource_routes())

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
            allow_methods=["*"],
            allow_headers=["*"],
        ),
        Middleware(RequestIDMiddleware),
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
