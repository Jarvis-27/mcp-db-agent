"""FastAPI REST API — user registration and management endpoints."""

import asyncio
import hashlib
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import create_engine, text

from src.api.schemas import (
    RegisterRequest,
    RegisterResponse,
    RotateKeyResponse,
    UpdateRequest,
    UserMetaResponse,
)
from src.auth.url_guard import InvalidDatabaseURL, validate_database_url
from src.auth.user_store import UserConfig, UserStore, User as UserModel
from src.config import settings

limiter = Limiter(key_func=get_remote_address)

api_app = FastAPI(title="MCP Database Analytics — Management API")
api_app.state.limiter = limiter
api_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


def _extract_raw_key(request: Request) -> str | None:
    key = request.headers.get("x-api-key")
    if key:
        return key.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def require_api_key(request: Request) -> UserConfig:
    """FastAPI dependency — authenticates via API key and returns UserConfig."""
    raw_key = _extract_raw_key(request)
    if not raw_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    user_store: UserStore = request.app.state.user_store
    cache = request.app.state.auth_key_cache

    cache_key = hashlib.sha256(raw_key.encode()).hexdigest()
    user_config: UserConfig | None = cache.get(cache_key)
    if user_config is None:
        user_config = user_store.get_user_by_api_key(raw_key)
        if user_config is None:
            raise HTTPException(status_code=401, detail="Invalid or inactive API key")
        cache[cache_key] = user_config

    return user_config


AuthedUser = Annotated[UserConfig, Depends(require_api_key)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dry_run_connect(database_url: str, timeout: int = 5) -> None:
    """Attempt a real connection to the database. Raises HTTPException on failure."""
    from sqlalchemy.engine import make_url

    try:
        url = make_url(database_url)
        connect_args = {}
        if url.drivername.startswith("postgresql"):
            connect_args = {"connect_timeout": timeout}
        engine = create_engine(
            database_url,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
    except Exception:
        # Never leak connection details in the error response
        raise HTTPException(
            status_code=400,
            detail=(
                "Could not connect to the provided database. "
                "Check your database_url credentials and ensure the database is reachable."
            ),
        )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@api_app.post("/v1/users/register", response_model=RegisterResponse, status_code=201)
@limiter.limit(settings.register_rate_limit)
async def register(request: Request, body: RegisterRequest) -> RegisterResponse:
    """Register a new user and return a one-time API key."""
    if not settings.registration_open:
        raise HTTPException(status_code=403, detail="Registration is currently closed.")

    # Validate URL (raises InvalidDatabaseURL → 400)
    try:
        validate_database_url(
            body.database_url, allow_sqlite=settings.allow_sqlite_user_dbs
        )
    except InvalidDatabaseURL as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Dry-run connect to fail fast on bad credentials
    await asyncio.to_thread(_dry_run_connect, body.database_url)

    user_store: UserStore = request.app.state.user_store
    user_id, raw_key = user_store.create_user(database_url=body.database_url)
    return RegisterResponse(user_id=user_id, api_key=raw_key)


# ---------------------------------------------------------------------------
# User self-service
# ---------------------------------------------------------------------------


@api_app.get("/v1/users/me", response_model=UserMetaResponse)
async def get_me(request: Request, user: AuthedUser) -> UserMetaResponse:
    """Return metadata for the authenticated user."""
    user_store: UserStore = request.app.state.user_store
    from sqlalchemy.orm import Session

    with Session(user_store._engine) as session:
        row = session.get(UserModel, user.user_id)
        if row is None:
            raise HTTPException(status_code=404, detail="User not found")
        return UserMetaResponse(
            user_id=row.id,
            is_active=row.is_active,
            created_at=row.created_at.isoformat(),
        )


@api_app.put("/v1/users/me", status_code=200)
async def update_me(request: Request, body: UpdateRequest, user: AuthedUser) -> dict:
    """Update the database URL for the authenticated user."""
    if body.database_url:
        try:
            validate_database_url(
                body.database_url, allow_sqlite=settings.allow_sqlite_user_dbs
            )
        except InvalidDatabaseURL as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        await asyncio.to_thread(_dry_run_connect, body.database_url)

    user_store: UserStore = request.app.state.user_store
    updated = user_store.update_user(user.user_id, database_url=body.database_url)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")

    # Invalidate cached pipeline for this user
    factory = getattr(request.app.state, "factory", None)
    if factory is not None:
        await factory.invalidate(user.user_id)

    # Bust auth-key cache for this user
    cache = request.app.state.auth_key_cache
    # Evict any entry matching this user_id (brute-force scan — cache is small)
    for k in list(cache.keys()):
        v = cache.get(k)
        if v is not None and v.user_id == user.user_id:
            del cache[k]

    return {"detail": "Updated successfully"}


@api_app.post("/v1/users/me/rotate-key", response_model=RotateKeyResponse)
@limiter.limit("10/hour")
async def rotate_key(request: Request, user: AuthedUser) -> RotateKeyResponse:
    """Issue a new API key, invalidating the current one."""
    user_store: UserStore = request.app.state.user_store
    new_raw_key = user_store.rotate_api_key(user.user_id)

    # Bust auth-key cache
    cache = request.app.state.auth_key_cache
    for k in list(cache.keys()):
        v = cache.get(k)
        if v is not None and v.user_id == user.user_id:
            del cache[k]

    # Invalidate pipeline cache
    factory = getattr(request.app.state, "factory", None)
    if factory is not None:
        await factory.invalidate(user.user_id)

    return RotateKeyResponse(api_key=new_raw_key)


@api_app.delete("/v1/users/me", status_code=204)
async def delete_me(request: Request, user: AuthedUser) -> Response:
    """Deactivate the authenticated user account."""
    user_store: UserStore = request.app.state.user_store
    user_store.deactivate_user(user.user_id)

    # Bust auth-key cache
    cache = request.app.state.auth_key_cache
    for k in list(cache.keys()):
        v = cache.get(k)
        if v is not None and v.user_id == user.user_id:
            del cache[k]

    # Invalidate pipeline cache
    factory = getattr(request.app.state, "factory", None)
    if factory is not None:
        await factory.invalidate(user.user_id)

    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------


@api_app.get("/health/live")
async def health_live() -> dict:
    """Process is up."""
    return {"status": "ok"}


@api_app.get("/health/ready")
async def health_ready(request: Request) -> dict:
    """Process is up, auth DB is reachable, and cipher is initialised."""
    try:
        user_store: UserStore = request.app.state.user_store
        with user_store._engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        # Verify cipher is initialised (it lives on the user_store)
        _ = user_store._cipher
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "detail": "Auth database not reachable"},
        )
    return {"status": "ok"}
