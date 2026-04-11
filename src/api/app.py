"""FastAPI REST API for tenant registration, owner sessions, and key management."""

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
    AdminStatusResponse,
    ApiKeyResponse,
    CreateApiKeyRequest,
    CreatedApiKeyResponse,
    GenericAcceptedResponse,
    OnboardingDatabaseResponse,
    OnboardingStatusResponse,
    OwnerSessionResponse,
    PendingTenantItem,
    RegisterRequest,
    RegistrationPendingResponse,
    RequestLoginLinkRequest,
    RotateKeyResponse,
    SubmitDatabaseRequest,
    TenantMetaResponse,
    UpdateRequest,
    VerifyEmailResponse,
)
from src.auth import onboarding
from src.auth.onboarding import (
    ACTIVE,
    CLOSED,
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
from src.auth.user_store import OwnerSessionContext, StateTransitionError, UserConfig, UserStore
from src.config import settings

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)

api_app = FastAPI(title="MCP Database Analytics - Management API")
api_app.state.limiter = limiter
api_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]


def _extract_raw_key(request: Request) -> str | None:
    key = request.headers.get("x-api-key")
    if key:
        return key.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def _extract_owner_session(request: Request) -> str | None:
    token = request.headers.get("x-owner-session")
    if token:
        return token.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def require_api_key(request: Request) -> UserConfig:
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


def require_owner_session(request: Request) -> OwnerSessionContext:
    raw_token = _extract_owner_session(request)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Missing owner session")

    user_store: UserStore = request.app.state.user_store
    cache = request.app.state.owner_session_cache

    cache_key = hashlib.sha256(raw_token.encode()).hexdigest()
    owner: OwnerSessionContext | None = cache.get(cache_key)
    if owner is None:
        owner = user_store.get_owner_by_session(raw_token)
        if owner is None:
            raise HTTPException(status_code=401, detail="Invalid or expired owner session")
        cache[cache_key] = owner

    return owner


def require_admin_key(request: Request) -> None:
    provided = request.headers.get("x-admin-key", "")
    expected = settings.admin_api_key or ""
    if not expected or not hmac.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Invalid or missing admin key")


AuthedUser = Annotated[UserConfig, Depends(require_api_key)]
AuthedOwner = Annotated[OwnerSessionContext, Depends(require_owner_session)]


def _dry_run_connect(database_url: str, timeout: int = 5) -> None:
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
        raise HTTPException(
            status_code=400,
            detail=(
                "Could not connect to the provided database. "
                "Check your database_url credentials and ensure the database is reachable."
            ),
        )


def _bust_tenant_caches(request: Request, tenant_id: str, api_key_id: str | None = None) -> None:
    auth_cache = request.app.state.auth_key_cache
    for key in list(auth_cache.keys()):
        value = auth_cache.get(key)
        if value is None:
            continue
        if value.user_id == tenant_id or (api_key_id is not None and value.api_key_id == api_key_id):
            del auth_cache[key]

    owner_cache = request.app.state.owner_session_cache
    for key in list(owner_cache.keys()):
        value = owner_cache.get(key)
        if value is not None and value.tenant_id == tenant_id:
            del owner_cache[key]

    factory = getattr(request.app.state, "factory", None)
    if factory is not None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(factory.invalidate(tenant_id))
        except Exception:
            pass


def _build_blockers(status: str) -> list[str]:
    if status == PENDING_EMAIL_VERIFICATION:
        return ["email_verification"]
    if status == "pending_billing":
        return ["billing"]
    if status == "pending_mfa":
        return ["mfa"]
    if status == PENDING_DB_CONNECTION:
        return ["database_connection"]
    if status == PENDING_REVIEW:
        return ["admin_review"]
    if status == SUSPENDED:
        return ["tenant_suspended"]
    if status == CLOSED:
        return ["tenant_closed"]
    return []


def _scopes_for_response(scope_text: str) -> list[str]:
    return [scope.strip() for scope in scope_text.split(",") if scope.strip()]


@api_app.post("/v1/users/register", response_model=RegistrationPendingResponse, status_code=201)
@limiter.limit(settings.register_rate_limit)
async def register(request: Request, body: RegisterRequest) -> RegistrationPendingResponse:
    if not settings.registration_open:
        raise HTTPException(status_code=403, detail="Registration is currently closed.")

    user_store: UserStore = request.app.state.user_store
    existing = user_store.get_owner_membership_by_email(body.email)
    if existing is not None and existing.onboarding_status != CLOSED:
        raise HTTPException(
            status_code=409,
            detail="An account with this email address already exists.",
        )

    tenant_id, membership_id = user_store.create_tenant_with_owner(
        email=body.email,
        tenant_name=body.tenant_name,
    )

    try:
        token_store: TokenStore = request.app.state.token_store
        raw_token = token_store.issue_email_verification_token(membership_id)
        verification_url = (
            f"{settings.app_base_url}/api/v1/onboarding/verify-email?token={raw_token}"
        )
        email_sender = request.app.state.email_sender
        email_sender.send_verification_email(body.email, verification_url)
    except Exception as exc:
        logger.warning("Failed to send verification email for tenant %s: %s", tenant_id, exc)

    return RegistrationPendingResponse(
        tenant_id=tenant_id,
        status=PENDING_EMAIL_VERIFICATION,
        message="Tenant created. Check your email and verify your address to continue.",
    )


@api_app.get("/v1/onboarding/verify-email", response_model=VerifyEmailResponse)
async def verify_email(
    token: str = Query(..., description="Email verification token from the verification link"),
    request: Request = ...,  # type: ignore[assignment]
) -> VerifyEmailResponse:
    token_store: TokenStore = request.app.state.token_store
    user_store: UserStore = request.app.state.user_store

    try:
        membership_id = token_store.verify_email_token(token)
    except TokenNotFoundError:
        raise HTTPException(status_code=400, detail="Invalid verification token.")
    except TokenExpiredError:
        raise HTTPException(status_code=400, detail="Verification token has expired.")
    except TokenAlreadyUsedError:
        raise HTTPException(status_code=400, detail="Verification token has already been used.")

    owner = user_store.get_owner_membership_by_id(membership_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Owner membership not found")
    if owner.onboarding_status != PENDING_EMAIL_VERIFICATION:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot verify email: tenant is in '{owner.onboarding_status}' state.",
        )

    user_store.set_email_verified(membership_id)
    new_state = onboarding.resolve_next_state(
        PENDING_EMAIL_VERIFICATION,
        TRIGGER_EMAIL_VERIFIED,
        billing_gate_enabled=settings.billing_gate_enabled,
        mfa_gate_enabled=settings.mfa_gate_enabled,
    )
    user_store.transition_tenant_state(owner.tenant_id, new_state)
    owner_session_token = user_store.issue_owner_session(
        membership_id,
        ttl_hours=settings.owner_session_ttl_hours,
    )

    return VerifyEmailResponse(
        tenant_id=owner.tenant_id,
        status=new_state,
        next_step=onboarding.get_next_step_description(new_state),
        owner_session_token=owner_session_token,
        expires_in_seconds=settings.owner_session_ttl_hours * 3600,
    )


@api_app.post("/v1/auth/request-login-link", response_model=GenericAcceptedResponse, status_code=202)
@limiter.limit("10/minute")
async def request_login_link(request: Request, body: RequestLoginLinkRequest) -> GenericAcceptedResponse:
    user_store: UserStore = request.app.state.user_store
    owner = user_store.get_owner_membership_by_email(body.email)

    if owner is not None:
        try:
            token_store: TokenStore = request.app.state.token_store
            raw_token = token_store.issue_owner_login_token(owner.membership_id)
            login_url = f"{settings.app_base_url}/api/v1/auth/exchange-login-link?token={raw_token}"
            request.app.state.email_sender.send_login_email(body.email, login_url)
        except Exception as exc:
            logger.warning("Failed to send login email for %s: %s", body.email, exc)

    return GenericAcceptedResponse(message="If an account exists, a sign-in link has been sent.")


@api_app.get("/v1/auth/exchange-login-link", response_model=OwnerSessionResponse)
async def exchange_login_link(
    token: str = Query(..., description="Owner login token from the email link"),
    request: Request = ...,  # type: ignore[assignment]
) -> OwnerSessionResponse:
    token_store: TokenStore = request.app.state.token_store
    user_store: UserStore = request.app.state.user_store

    try:
        membership_id = token_store.verify_owner_login_token(token)
    except TokenNotFoundError:
        raise HTTPException(status_code=400, detail="Invalid login token.")
    except TokenExpiredError:
        raise HTTPException(status_code=400, detail="Login token has expired.")
    except TokenAlreadyUsedError:
        raise HTTPException(status_code=400, detail="Login token has already been used.")

    owner = user_store.get_owner_membership_by_id(membership_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Owner membership not found")

    owner_session_token = user_store.issue_owner_session(
        membership_id,
        ttl_hours=settings.owner_session_ttl_hours,
    )
    return OwnerSessionResponse(
        tenant_id=owner.tenant_id,
        status=owner.onboarding_status,
        owner_session_token=owner_session_token,
        expires_in_seconds=settings.owner_session_ttl_hours * 3600,
    )


@api_app.post("/v1/auth/logout", status_code=204)
async def logout(request: Request, owner: AuthedOwner) -> Response:
    raw_token = _extract_owner_session(request)
    if raw_token:
        request.app.state.user_store.revoke_owner_session(raw_token)
    _bust_tenant_caches(request, owner.tenant_id)
    return Response(status_code=204)


@api_app.get("/v1/onboarding/status", response_model=OnboardingStatusResponse)
async def onboarding_status(owner: AuthedOwner, request: Request) -> OnboardingStatusResponse:
    user_store: UserStore = request.app.state.user_store
    status = user_store.get_tenant_status(owner.tenant_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return OnboardingStatusResponse(
        tenant_id=owner.tenant_id,
        status=status,
        next_step=onboarding.get_next_step_description(status),
        blockers=_build_blockers(status),
        can_issue_api_key=user_store.owner_can_issue_api_keys(owner.tenant_id),
    )


@api_app.post("/v1/onboarding/database", response_model=OnboardingDatabaseResponse)
async def submit_database(
    body: SubmitDatabaseRequest,
    request: Request,
    owner: AuthedOwner,
) -> OnboardingDatabaseResponse:
    user_store: UserStore = request.app.state.user_store
    current_status = user_store.get_tenant_status(owner.tenant_id)
    if current_status != PENDING_DB_CONNECTION:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot submit database: tenant is in '{current_status}' state.",
        )

    try:
        sanitized_url = validate_database_url(
            body.database_url, allow_sqlite=settings.allow_sqlite_user_dbs
        )
    except InvalidDatabaseURL as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    sanitized_url_str = sanitized_url.render_as_string(hide_password=False)
    await asyncio.to_thread(_dry_run_connect, sanitized_url_str)

    encrypted_url = request.app.state.cipher.encrypt(sanitized_url_str)
    user_store.upsert_active_database(owner.tenant_id, encrypted_url, name=(body.name or "primary"))
    onboarding.resolve_next_state(PENDING_DB_CONNECTION, TRIGGER_DB_SUBMITTED)
    user_store.transition_tenant_state(owner.tenant_id, PENDING_REVIEW)
    _bust_tenant_caches(request, owner.tenant_id)

    return OnboardingDatabaseResponse(
        tenant_id=owner.tenant_id,
        status=PENDING_REVIEW,
        next_step=onboarding.get_next_step_description(PENDING_REVIEW),
    )


@api_app.get("/v1/admin/tenants/pending", response_model=list[PendingTenantItem])
async def list_pending_tenants(
    request: Request,
    _: None = Depends(require_admin_key),
) -> list[PendingTenantItem]:
    user_store: UserStore = request.app.state.user_store
    rows = user_store.list_tenants_by_status(PENDING_REVIEW)
    return [
        PendingTenantItem(
            tenant_id=str(tenant.id),
            owner_email=None if owner is None else owner.email,
            created_at=tenant.created_at.isoformat(),
            onboarding_status=str(tenant.status),
        )
        for tenant, owner in rows
    ]


@api_app.post("/v1/admin/tenants/{tenant_id}/approve", response_model=AdminStatusResponse)
async def approve_tenant(
    tenant_id: str,
    request: Request,
    _: None = Depends(require_admin_key),
) -> AdminStatusResponse:
    user_store: UserStore = request.app.state.user_store
    current_status = user_store.get_tenant_status(tenant_id)
    if current_status is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if current_status != PENDING_REVIEW:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot approve: tenant is in '{current_status}' state, expected '{PENDING_REVIEW}'.",
        )

    user_store.transition_tenant_state(tenant_id, ACTIVE)
    _bust_tenant_caches(request, tenant_id)
    return AdminStatusResponse(tenant_id=tenant_id, status=ACTIVE)


@api_app.post("/v1/admin/tenants/{tenant_id}/suspend", response_model=AdminStatusResponse)
async def suspend_tenant(
    tenant_id: str,
    request: Request,
    _: None = Depends(require_admin_key),
) -> AdminStatusResponse:
    user_store: UserStore = request.app.state.user_store
    current_status = user_store.get_tenant_status(tenant_id)
    if current_status is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    try:
        onboarding.resolve_next_state(current_status, TRIGGER_ADMIN_SUSPENDED)
    except InvalidTransitionError:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot suspend: tenant is in '{current_status}' state.",
        )

    user_store.transition_tenant_state(tenant_id, SUSPENDED)
    _bust_tenant_caches(request, tenant_id)
    return AdminStatusResponse(tenant_id=tenant_id, status=SUSPENDED)


@api_app.post("/v1/admin/tenants/{tenant_id}/close", response_model=AdminStatusResponse)
async def close_tenant(
    tenant_id: str,
    request: Request,
    _: None = Depends(require_admin_key),
) -> AdminStatusResponse:
    user_store: UserStore = request.app.state.user_store
    current_status = user_store.get_tenant_status(tenant_id)
    if current_status is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    try:
        onboarding.resolve_next_state(current_status, TRIGGER_ADMIN_CLOSED)
    except InvalidTransitionError:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot close: tenant is in '{current_status}' state.",
        )

    user_store.transition_tenant_state(tenant_id, CLOSED)
    _bust_tenant_caches(request, tenant_id)
    return AdminStatusResponse(tenant_id=tenant_id, status=CLOSED)


@api_app.post("/v1/api-keys", response_model=CreatedApiKeyResponse, status_code=201)
async def create_api_key(
    body: CreateApiKeyRequest,
    request: Request,
    owner: AuthedOwner,
) -> CreatedApiKeyResponse:
    allowed_scopes = {"mcp_read", "api_key_admin"}
    bad_scopes = [scope for scope in body.scopes if scope not in allowed_scopes]
    if bad_scopes:
        raise HTTPException(status_code=400, detail=f"Unsupported scopes: {', '.join(bad_scopes)}")

    user_store: UserStore = request.app.state.user_store
    try:
        raw_key, api_key = user_store.create_api_key(
            tenant_id=owner.tenant_id,
            name=body.name,
            scopes=body.scopes,
            created_by_membership_id=owner.membership_id,
        )
    except StateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    _bust_tenant_caches(request, owner.tenant_id)
    return CreatedApiKeyResponse(
        id=str(api_key.id),
        name=str(api_key.name),
        prefix=str(api_key.prefix),
        scopes=_scopes_for_response(str(api_key.scope)),
        created_at=api_key.created_at.isoformat(),
        last_used_at=None,
        revoked_at=None,
        api_key=raw_key,
    )


@api_app.get("/v1/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(request: Request, owner: AuthedOwner) -> list[ApiKeyResponse]:
    user_store: UserStore = request.app.state.user_store
    rows = user_store.list_api_keys(owner.tenant_id)
    return [
        ApiKeyResponse(
            id=str(row.id),
            name=str(row.name),
            prefix=str(row.prefix),
            scopes=_scopes_for_response(str(row.scope)),
            created_at=row.created_at.isoformat(),
            last_used_at=None if row.last_used_at is None else row.last_used_at.isoformat(),
            revoked_at=None if row.revoked_at is None else row.revoked_at.isoformat(),
        )
        for row in rows
    ]


@api_app.delete("/v1/api-keys/{api_key_id}", status_code=204)
async def revoke_api_key(api_key_id: str, request: Request, owner: AuthedOwner) -> Response:
    user_store: UserStore = request.app.state.user_store
    revoked = user_store.revoke_api_key(owner.tenant_id, api_key_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="API key not found")
    _bust_tenant_caches(request, owner.tenant_id, api_key_id=api_key_id)
    return Response(status_code=204)


@api_app.get("/v1/users/me", response_model=TenantMetaResponse)
async def get_me(request: Request, user: AuthedUser) -> TenantMetaResponse:
    user_store: UserStore = request.app.state.user_store
    tenant = user_store.get_tenant(user.user_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return TenantMetaResponse(
        tenant_id=str(tenant.id),
        is_active=str(tenant.status) == ACTIVE,
        created_at=tenant.created_at.isoformat(),
        status=str(tenant.status),
    )


@api_app.put("/v1/users/me", status_code=200)
async def update_me(request: Request, body: UpdateRequest, user: AuthedUser) -> dict:
    if user.onboarding_status != ACTIVE:
        raise HTTPException(
            status_code=403,
            detail="Tenant must be active to update the registered database.",
        )

    if body.database_url:
        try:
            sanitized_url = validate_database_url(
                body.database_url, allow_sqlite=settings.allow_sqlite_user_dbs
            )
        except InvalidDatabaseURL as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        sanitized_url_str = sanitized_url.render_as_string(hide_password=False)
        await asyncio.to_thread(_dry_run_connect, sanitized_url_str)
        encrypted = request.app.state.cipher.encrypt(sanitized_url_str)
        request.app.state.user_store.upsert_active_database(user.user_id, encrypted, name="primary")

    _bust_tenant_caches(request, user.user_id)
    return {"detail": "Updated successfully"}


@api_app.post("/v1/users/me/rotate-key", response_model=RotateKeyResponse)
@limiter.limit("10/hour")
async def rotate_key(request: Request, user: AuthedUser) -> RotateKeyResponse:
    if user.api_key_id is None:
        raise HTTPException(status_code=409, detail="Current key metadata is unavailable.")
    user_store: UserStore = request.app.state.user_store
    try:
        new_raw_key = user_store.rotate_api_key(user.user_id, user.api_key_id)
    except (StateTransitionError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    _bust_tenant_caches(request, user.user_id, api_key_id=user.api_key_id)
    return RotateKeyResponse(api_key=new_raw_key)


@api_app.delete("/v1/users/me", status_code=410)
async def delete_me(_: Request, __: AuthedUser) -> Response:
    raise HTTPException(
        status_code=410,
        detail="DELETE /v1/users/me is deprecated. Close the tenant via an owner session or admin action.",
    )


@api_app.get("/health/live")
async def health_live() -> dict:
    return {"status": "ok"}


@api_app.get("/health/ready")
async def health_ready(request: Request) -> dict:
    try:
        user_store: UserStore = request.app.state.user_store
        with user_store._engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        _ = user_store._cipher
    except Exception:
        raise HTTPException(status_code=503, detail="Auth database not reachable")
    return {"status": "ok"}
