"""Combined ASGI entry point for hosted multi-tenant deployment.

Stdio single-user mode:  uv run src/server.py  (does NOT use this file)
Hosted HTTP mode:        uv run uvicorn src.app:app --workers 4 ...
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
from src.auth.middleware import ApiKeyMiddleware
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


@asynccontextmanager
async def lifespan(app: Starlette):
    """Unified lifespan — starts all shared resources, tears them down on exit."""

    # 1. Build cipher (fails loud if no encryption key in non-dev mode)
    keys = settings.credential_encryption_keys_list()
    if not keys:
        # Development fallback — generate an ephemeral key so the server starts
        # without CREDENTIAL_ENCRYPTION_KEYS set in .env.
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
            # Fall back to create_all so tests work without a migration chain
            from src.auth.user_store import Base

            Base.metadata.create_all(auth_engine)
    else:
        # Production: verify schema is at the Alembic head revision.
        # expected_head is read from the script directory so this check
        # never needs updating when new migrations are added.
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

    # 4. Build UserStore, auth-key cache, executor pool, query log, pipeline factory
    user_store = UserStore(auth_engine, cipher)
    auth_key_cache: TTLCache = TTLCache(maxsize=10_000, ttl=60)
    owner_session_cache: TTLCache = TTLCache(maxsize=10_000, ttl=60)
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
    api_app.state.owner_session_cache = owner_session_cache
    api_app.state.factory = factory
    api_app.state.token_store = token_store
    api_app.state.email_sender = email_sender
    api_app.state.cipher = cipher
    api_app.state.query_log = query_log

    # Also stash on the parent Starlette app's state so _AuthedMCPWrapper can read it
    app.state.user_store = user_store
    app.state.auth_key_cache = auth_key_cache
    app.state.owner_session_cache = owner_session_cache

    # 7. Stash factory and query_log on server module for MCP tool handlers
    server_module = importlib.import_module("src.server")
    server_module._factory = factory  # type: ignore[attr-defined]
    server_module._query_log = query_log  # type: ignore[attr-defined]
    server_module._user_store = user_store  # type: ignore[attr-defined]

    log.info("MCP Database Analytics Agent started (hosted multi-tenant mode)")

    # Start the FastMCP session manager — required for streamable HTTP transport.
    # The sub-app lifespan is not automatically forwarded through _AuthedMCPWrapper,
    # so we run it explicitly here.
    async with _server_module.mcp.session_manager.run():
        try:
            yield
        finally:
            log.info("Shutting down...")
            await factory.shutdown()
            executor_pool.shutdown(wait=False, cancel_futures=True)
            auth_engine.dispose()


# ---------------------------------------------------------------------------
# Build the MCP ASGI app
# ---------------------------------------------------------------------------

# Reuse the same FastMCP instance from server.py — all tools are registered on it.
_mcp_app = _server_module.mcp.streamable_http_app()

# ---------------------------------------------------------------------------
# Parent Starlette app — lifespan lives HERE, not on sub-apps
# ---------------------------------------------------------------------------

app = Starlette(
    lifespan=lifespan,
    routes=[
        Mount("/api", app=api_app),
        # ApiKeyMiddleware is applied at runtime after lifespan populates user_store.
        # We use a small ASGI wrapper so the middleware sees the populated state.
        Mount("/mcp", app=_mcp_app),
    ],
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


class _AuthedMCPWrapper:
    """Wrap the MCP ASGI app with ApiKeyMiddleware after startup.

    ApiKeyMiddleware needs user_store from app.state, which is only available
    after lifespan startup. This wrapper defers construction of the middleware
    to the first request.
    """

    def __init__(self, inner_app, starlette_app: Starlette) -> None:
        self._inner = inner_app
        self._starlette_app = starlette_app
        self._authed: ApiKeyMiddleware | None = None

    async def __call__(self, scope, receive, send):
        if self._authed is None and scope["type"] == "http":
            user_store = self._starlette_app.state.user_store
            cache = self._starlette_app.state.auth_key_cache
            self._authed = ApiKeyMiddleware(self._inner, user_store=user_store, cache=cache)
        if self._authed is not None:
            await self._authed(scope, receive, send)
        else:
            await self._inner(scope, receive, send)


# Replace the plain MCP mount with the auth-wrapped version
app.routes[1] = Mount("/mcp", app=_AuthedMCPWrapper(_mcp_app, app))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.app:app",
        host="0.0.0.0",
        port=settings.port,
        proxy_headers=True,
        forwarded_allow_ips=settings.trusted_proxy_ips or "127.0.0.1",
    )
