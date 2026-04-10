"""FastAPI REST API — user registration, onboarding, and management endpoints."""

import asyncio
import hashlib
import hmac
import logging
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import create_engine, text

from src.api.schemas import (
    AdminApproveResponse,
    AdminStatusResponse,
    OnboardingDatabaseResponse,
    OnboardingStatusResponse,
    PendingUserItem,
    RegisterRequest,
    RegistrationPendingResponse,
    RotateKeyResponse,
    SubmitDatabaseRequest,
    UpdateRequest,
    UserMetaResponse,
    VerifyEmailResponse,
)
from src.auth import onboarding
from src.auth.onboarding import (
    ACTIVE,
    PENDING_DB_CONNECTION,
    PENDING_EMAIL_VERIFICATION,
    PENDING_REVIEW,
    SUSPENDED,
    TRIGGER_ADMIN_CLOSED,
    TRIGGER_ADMIN_SUSPENDED,
    TRIGGER_DB_SUBMITTED,
    TRIGGER_EMAIL_VERIFIED,
    InvalidTransitionError,
)
from src.auth.token_store import (
    TokenAlreadyUsedError,
    TokenExpiredError,
    TokenNotFoundError,
    TokenStore,
)
from src.auth.url_guard import InvalidDatabaseURL, validate_database_url
from src.auth.user_store import StateTransitionError, UserConfig, UserStore, User as UserModel
from src.config import settings

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)

api_app = FastAPI(title="MCP Database Analytics — Management API")
api_app.state.limiter = limiter
api_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Auth dependencies
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


def require_admin_key(request: Request) -> None:
    """FastAPI dependency — validates X-Admin-Key header against settings.admin_api_key."""
    provided = request.headers.get("x-admin-key", "")
    expected = settings.admin_api_key or ""
    if not expected or not hmac.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Invalid or missing admin key")


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


def _bust_user_caches(request: Request, user_id: str) -> None:
    """Evict auth-key cache and pipeline cache entries for the given user."""
    cache = request.app.state.auth_key_cache
    for k in list(cache.keys()):
        v = cache.get(k)
        if v is not None and v.user_id == user_id:
            del cache[k]

    factory = getattr(request.app.state, "factory", None)
    if factory is not None:
        import asyncio as _asyncio
        try:
            loop = _asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(factory.invalidate(user_id))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@api_app.post("/v1/users/register", response_model=RegistrationPendingResponse, status_code=201)
@limiter.limit(settings.register_rate_limit)
async def register(request: Request, body: RegisterRequest) -> RegistrationPendingResponse:
    """Register a new account with email only. Returns a pending user — no API key is issued.

    A verification email is sent to the provided address. The user must complete
    email verification, then submit database connection details, and await admin
    approval before an API key can be issued.
    """
    if not settings.registration_open:
        raise HTTPException(status_code=403, detail="Registration is currently closed.")

    user_store: UserStore = request.app.state.user_store

    # Duplicate-email guard
    existing = user_store.get_user_by_email(body.email)
    if existing is not None and existing.onboarding_status != "closed":
        raise HTTPException(
            status_code=409,
            detail="An account with this email address already exists.",
        )

    user_id = user_store.create_user(email=body.email)

    # Issue verification token and send email (best-effort; log on failure)
    try:
        token_store: TokenStore = request.app.state.token_store
        raw_token = token_store.issue_email_verification_token(user_id)
        verification_url = (
            f"{settings.app_base_url}/api/v1/onboarding/verify-email?token={raw_token}"
        )
        email_sender = request.app.state.email_sender
        email_sender.send_verification_email(body.email, verification_url)
    except Exception as exc:
        logger.warning("Failed to send verification email for user %s: %s", user_id, exc)

    return RegistrationPendingResponse(
        user_id=user_id,
        status="pending_email_verification",
        message="Account created. Check your email and verify your address to continue.",
    )


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------


@api_app.get("/v1/onboarding/status", response_model=OnboardingStatusResponse)
async def onboarding_status(user_id: str, request: Request) -> OnboardingStatusResponse:
    """Return the current onboarding state for a pending or active user."""
    user_store: UserStore = request.app.state.user_store
    status = user_store.get_onboarding_status(user_id)
    if status is None:
        raise HTTPException(status_code=404, detail="User not found")
    return OnboardingStatusResponse(
        user_id=user_id,
        status=status,
        next_step=onboarding.get_next_step_description(status),
    )


@api_app.get("/v1/onboarding/verify-email", response_model=VerifyEmailResponse)
async def verify_email(
    token: str = Query(..., description="Email verification token from the verification link"),
    request: Request = ...,  # type: ignore[assignment]
) -> VerifyEmailResponse:
    """Verify the user's email address using the token from the verification email.

    On success, returns a setup_token that must be used to submit database
    connection details (POST /v1/onboarding/database).
    """
    token_store: TokenStore = request.app.state.token_store
    user_store: UserStore = request.app.state.user_store

    # Validate and consume the email verification token
    try:
        user_id = token_store.verify_email_token(token)
    except TokenNotFoundError:
        raise HTTPException(status_code=400, detail="Invalid verification token.")
    except TokenExpiredError:
        raise HTTPException(
            status_code=400,
            detail="Verification token has expired. Please register again or request a new link.",
        )
    except TokenAlreadyUsedError:
        raise HTTPException(status_code=400, detail="Verification token has already been used.")

    # Check current state
    current_status = user_store.get_onboarding_status(user_id)
    if current_status != PENDING_EMAIL_VERIFICATION:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot verify email: account is in '{current_status}' state.",
        )

    # Record email as verified
    user_store.set_email_verified(user_id)

    # Advance state (auto-skip billing/MFA if gates are disabled)
    new_state = onboarding.resolve_next_state(
        PENDING_EMAIL_VERIFICATION,
        TRIGGER_EMAIL_VERIFIED,
        billing_gate_enabled=settings.billing_gate_enabled,
        mfa_gate_enabled=settings.mfa_gate_enabled,
    )
    user_store.transition_state(user_id, new_state)

    # Issue a setup token for the next onboarding step
    setup_token = token_store.issue_setup_token(user_id)

    return VerifyEmailResponse(
        user_id=user_id,
        status=new_state,
        next_step=onboarding.get_next_step_description(new_state),
        setup_token=setup_token,
    )


@api_app.post("/v1/onboarding/database", response_model=OnboardingDatabaseResponse)
async def submit_database(
    body: SubmitDatabaseRequest,
    request: Request,
) -> OnboardingDatabaseResponse:
    """Submit database connection details.

    Requires a valid setup_token (obtained from the email verification step).
    Validates the connection, stores the encrypted URL, and advances the account
    to 'pending_review' for admin approval.
    """
    token_store: TokenStore = request.app.state.token_store
    user_store: UserStore = request.app.state.user_store

    # Validate setup token
    try:
        user_id = token_store.verify_setup_token(body.setup_token)
    except TokenNotFoundError:
        raise HTTPException(status_code=400, detail="Invalid setup token.")
    except TokenExpiredError:
        raise HTTPException(
            status_code=400,
            detail="Setup token has expired. Please complete email verification again.",
        )

    # Enforce state: must be in pending_db_connection
    current_status = user_store.get_onboarding_status(user_id)
    if current_status != PENDING_DB_CONNECTION:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot submit database: account is in '{current_status}' state.",
        )

    # Validate and dry-run connect
    try:
        sanitized_url = validate_database_url(
            body.database_url, allow_sqlite=settings.allow_sqlite_user_dbs
        )
    except InvalidDatabaseURL as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    sanitized_url_str = sanitized_url.render_as_string(hide_password=False)
    await asyncio.to_thread(_dry_run_connect, sanitized_url_str)

    # Store encrypted URL
    from src.auth.crypto import CredentialCipher
    cipher: CredentialCipher = request.app.state.cipher
    encrypted_url = cipher.encrypt(sanitized_url_str)
    user_store.set_database_url(user_id, encrypted_url)

    # Advance state to pending_review
    user_store.transition_state(user_id, PENDING_REVIEW)

    # Revoke the setup token — it has served its purpose
    token_store.revoke_setup_token(user_id)

    return OnboardingDatabaseResponse(
        user_id=user_id,
        status=PENDING_REVIEW,
        next_step=onboarding.get_next_step_description(PENDING_REVIEW),
    )


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@api_app.get("/v1/admin/users/pending", response_model=list[PendingUserItem])
async def list_pending_users(
    request: Request,
    _: None = Depends(require_admin_key),
) -> list[PendingUserItem]:
    """List all users in 'pending_review' state (awaiting admin approval)."""
    user_store: UserStore = request.app.state.user_store
    users = user_store.list_users_by_status(PENDING_REVIEW)
    return [
        PendingUserItem(
            user_id=str(u.id),
            email=u.email,  # type: ignore[arg-type]
            created_at=u.created_at.isoformat(),
            onboarding_status=str(u.onboarding_status),
        )
        for u in users
    ]


@api_app.post("/v1/admin/users/{user_id}/approve", response_model=AdminApproveResponse)
async def approve_user(
    user_id: str,
    request: Request,
    _: None = Depends(require_admin_key),
) -> AdminApproveResponse:
    """Approve a user in 'pending_review' state.

    Advances the account to 'active', issues the first API key, and optionally
    sends the key to the user via email. The raw API key is returned in this
    response — handle it securely.
    """
    user_store: UserStore = request.app.state.user_store

    current_status = user_store.get_onboarding_status(user_id)
    if current_status is None:
        raise HTTPException(status_code=404, detail="User not found")
    if current_status != PENDING_REVIEW:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot approve: user is in '{current_status}' state, expected 'pending_review'.",
        )

    try:
        api_key = user_store.issue_first_api_key(user_id)
    except StateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # Best-effort: send API key to user via email
    user_config = user_store.get_user_by_id(user_id)
    if user_config and user_config.email:
        try:
            email_sender = request.app.state.email_sender
            email_sender.send_api_key_email(user_config.email, api_key)
        except Exception as exc:
            logger.warning("Failed to send API key email for user %s: %s", user_id, exc)

    return AdminApproveResponse(
        user_id=user_id,
        status=ACTIVE,
        api_key=api_key,
    )


@api_app.post("/v1/admin/users/{user_id}/suspend", response_model=AdminStatusResponse)
async def suspend_user(
    user_id: str,
    request: Request,
    _: None = Depends(require_admin_key),
) -> AdminStatusResponse:
    """Suspend an active user account."""
    user_store: UserStore = request.app.state.user_store

    current_status = user_store.get_onboarding_status(user_id)
    if current_status is None:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        onboarding.resolve_next_state(current_status, TRIGGER_ADMIN_SUSPENDED)
    except InvalidTransitionError:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot suspend: user is in '{current_status}' state.",
        )

    user_store.transition_state(user_id, SUSPENDED)
    _bust_user_caches(request, user_id)

    return AdminStatusResponse(user_id=user_id, status=SUSPENDED)


@api_app.post("/v1/admin/users/{user_id}/close", response_model=AdminStatusResponse)
async def close_user(
    user_id: str,
    request: Request,
    _: None = Depends(require_admin_key),
) -> AdminStatusResponse:
    """Permanently close a user account."""
    user_store: UserStore = request.app.state.user_store

    current_status = user_store.get_onboarding_status(user_id)
    if current_status is None:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        onboarding.resolve_next_state(current_status, TRIGGER_ADMIN_CLOSED)
    except InvalidTransitionError:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot close: user is in '{current_status}' state.",
        )

    user_store.transition_state(user_id, "closed")
    _bust_user_caches(request, user_id)

    return AdminStatusResponse(user_id=user_id, status="closed")


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
            user_id=row.id,  # type: ignore[arg-type]
            is_active=row.is_active,  # type: ignore[arg-type]
            created_at=row.created_at.isoformat(),
        )


@api_app.put("/v1/users/me", status_code=200)
async def update_me(request: Request, body: UpdateRequest, user: AuthedUser) -> dict:
    """Update the database URL for the authenticated user."""
    if user.onboarding_status != "active":
        raise HTTPException(
            status_code=403,
            detail="Account must be active to update database connection.",
        )

    sanitized_url_str: str | None = None
    if body.database_url:
        try:
            sanitized_url = validate_database_url(
                body.database_url, allow_sqlite=settings.allow_sqlite_user_dbs
            )
        except InvalidDatabaseURL as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        sanitized_url_str = sanitized_url.render_as_string(hide_password=False)
        await asyncio.to_thread(_dry_run_connect, sanitized_url_str)

    user_store: UserStore = request.app.state.user_store
    updated = user_store.update_user(user.user_id, database_url=sanitized_url_str)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")

    _bust_user_caches(request, user.user_id)

    return {"detail": "Updated successfully"}


@api_app.post("/v1/users/me/rotate-key", response_model=RotateKeyResponse)
@limiter.limit("10/hour")
async def rotate_key(request: Request, user: AuthedUser) -> RotateKeyResponse:
    """Issue a new API key, invalidating the current one."""
    user_store: UserStore = request.app.state.user_store
    new_raw_key = user_store.rotate_api_key(user.user_id)
    _bust_user_caches(request, user.user_id)
    return RotateKeyResponse(api_key=new_raw_key)


@api_app.delete("/v1/users/me", status_code=204)
async def delete_me(request: Request, user: AuthedUser) -> Response:
    """Deactivate the authenticated user account."""
    user_store: UserStore = request.app.state.user_store
    user_store.deactivate_user(user.user_id)
    _bust_user_caches(request, user.user_id)
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
        raise HTTPException(
            status_code=503,
            detail="Auth database not reachable",
        )
    return {"status": "ok"}
