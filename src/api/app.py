"""FastAPI REST API — user account management, auth, and key management."""

import asyncio
import hashlib
import json
import logging
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import create_engine, text

from src.api.schemas import (
    AccountResponse,
    AccountStatusResponse,
    ActiveDatabaseSummary,
    ApiKeyResponse,
    ClientSetupPayloadResponse,
    CreateApiKeyRequest,
    CreatedApiKeyResponse,
    DashboardSummaryResponse,
    DatabaseResponse,
    GenericAcceptedResponse,
    OAuthLinkStartResponse,
    OAuthLinkStatusResponse,
    OAuthUnlinkResponse,
    QuotaSummary,
    RecentQueryItem,
    RequestLoginLinkRequest,
    RotateKeyResponse,
    SessionResponse,
    SetupApiKeyStateResponse,
    SetupClientsResponse,
    SetupPayloadRequest,
    SetupPayloadResponse,
    SetupQuotaSummaryResponse,
    SignupPendingResponse,
    SignupRequest,
    SubmitDatabaseRequest,
    UsageRecentResponse,
    VerifyEmailResponse,
)
from src.auth import onboarding
from src.auth.onboarding import (
    ACCOUNT_ACTIVE,
    ACCOUNT_CLOSED,
    ACCOUNT_SUSPENDED,
    PENDING_DB_CONNECTION,
    PENDING_EMAIL_VERIFICATION,
    SETUP_COMPLETE,
    TRIGGER_EMAIL_VERIFIED,
)
from src.auth.token_store import (
    TokenAlreadyUsedError,
    TokenExpiredError,
    TokenNotFoundError,
    TokenStore,
)
from src.auth.url_guard import InvalidDatabaseURL, validate_database_url
from src.auth.user_store import (
    EntitlementExceededError,
    StateTransitionError,
    UserConfig,
    UserSessionContext,
    UserStore,
)
from src.config import settings
from src.entitlements.service import EntitlementService
from src.setup import SetupPayloadEligibilityError, SetupPayloadInputError, SetupPayloadService

_entitlements = EntitlementService()

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)

api_app = FastAPI(title="MCP Database Analytics - Account API")
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


def _extract_session_token(request: Request) -> str | None:
    token = request.headers.get("x-session-token")
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


def require_user_session(request: Request) -> UserSessionContext:
    raw_token = _extract_session_token(request)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Missing session token")

    user_store: UserStore = request.app.state.user_store
    cache = request.app.state.user_session_cache

    cache_key = hashlib.sha256(raw_token.encode()).hexdigest()
    ctx: UserSessionContext | None = cache.get(cache_key)
    if ctx is None:
        ctx = user_store.get_user_by_session(raw_token)
        if ctx is None:
            raise HTTPException(status_code=401, detail="Invalid or expired session token")
        cache[cache_key] = ctx

    return ctx


AuthedUser = Annotated[UserConfig, Depends(require_api_key)]
AuthedSession = Annotated[UserSessionContext, Depends(require_user_session)]


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


def _bust_user_caches(request: Request, user_id: str, api_key_id: str | None = None) -> None:
    auth_cache = request.app.state.auth_key_cache
    for key in list(auth_cache.keys()):
        value = auth_cache.get(key)
        if value is None:
            continue
        if value.user_id == user_id or (
            api_key_id is not None and value.api_key_id == api_key_id
        ):
            del auth_cache[key]

    session_cache = request.app.state.user_session_cache
    for key in list(session_cache.keys()):
        value = session_cache.get(key)
        if value is not None and value.user_id == user_id:
            del session_cache[key]

    factory = getattr(request.app.state, "factory", None)
    if factory is not None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(factory.invalidate(user_id))
        except Exception:
            pass


def _build_blockers(onboarding_status: str, account_status: str) -> list[str]:
    blockers: list[str] = []
    if onboarding_status == PENDING_EMAIL_VERIFICATION:
        blockers.append("email_verification")
    elif onboarding_status == PENDING_DB_CONNECTION:
        blockers.append("database_connection")
    if account_status == ACCOUNT_SUSPENDED:
        blockers.append("account_suspended")
    elif account_status == ACCOUNT_CLOSED:
        blockers.append("account_closed")
    return blockers


def _scopes_for_response(scope_text: str) -> list[str]:
    return [scope.strip() for scope in scope_text.split(",") if scope.strip()]


def _entitlement_conflict_response(exc: EntitlementExceededError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "detail": str(exc),
            "code": exc.code,
            "plan_code": exc.plan_code,
            "current": exc.current,
            "limit": exc.limit,
        },
    )


def _client_setup_response(payload) -> ClientSetupPayloadResponse:
    return ClientSetupPayloadResponse(
        client_id=payload.client_id,
        display_name=payload.display_name,
        status=payload.status,
        auth_method=payload.auth_method,
        config_path_hint=payload.config_path_hint,
        snippet_format=payload.snippet_format,
        snippet=payload.snippet,
        api_key_handling=payload.api_key_handling,
        instructions=list(payload.instructions),
        availability_reason=payload.availability_reason,
    )


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------


@api_app.post("/v1/auth/signup", response_model=SignupPendingResponse, status_code=201)
@limiter.limit(settings.register_rate_limit)
async def signup(request: Request, body: SignupRequest) -> SignupPendingResponse:
    if not settings.registration_open:
        raise HTTPException(status_code=403, detail="Registration is currently closed.")

    user_store: UserStore = request.app.state.user_store
    if user_store.email_exists(body.email):
        raise HTTPException(
            status_code=409,
            detail="An account with this email address already exists.",
        )

    user_id = user_store.create_user(email=body.email)

    try:
        token_store: TokenStore = request.app.state.token_store
        raw_token = token_store.issue_email_verification_token(user_id)
        verification_url = f"{settings.frontend_base_url}/auth/verify?token={raw_token}"
        email_sender = request.app.state.email_sender
        email_sender.send_verification_email(body.email, verification_url)
    except Exception as exc:
        logger.warning("Failed to send verification email for user %s: %s", user_id, exc)

    return SignupPendingResponse(
        user_id=user_id,
        status=PENDING_EMAIL_VERIFICATION,
        message="Account created. Check your email and verify your address to continue.",
    )


@api_app.get("/v1/auth/verify-email", response_model=VerifyEmailResponse)
async def verify_email(
    token: str = Query(..., description="Email verification token from the verification link"),
    request: Request = ...,  # type: ignore[assignment]
) -> VerifyEmailResponse:
    token_store: TokenStore = request.app.state.token_store
    user_store: UserStore = request.app.state.user_store

    try:
        user_id = token_store.verify_email_token(token)
    except TokenNotFoundError:
        raise HTTPException(status_code=400, detail="Invalid verification token.")
    except TokenExpiredError:
        raise HTTPException(status_code=400, detail="Verification token has expired.")
    except TokenAlreadyUsedError:
        raise HTTPException(status_code=400, detail="Verification token has already been used.")

    user = user_store.get_user_row(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if str(user.onboarding_status) != PENDING_EMAIL_VERIFICATION:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot verify email: account is in '{user.onboarding_status}' state.",
        )

    user_store.set_email_verified(user_id)
    new_state = onboarding.resolve_next_state(
        PENDING_EMAIL_VERIFICATION,
        TRIGGER_EMAIL_VERIFIED,
    )
    user_store.transition_user_state(user_id, new_state)
    session_token = user_store.issue_user_session(
        user_id,
        ttl_hours=settings.user_session_ttl_hours,
    )

    return VerifyEmailResponse(
        user_id=user_id,
        status=new_state,
        next_step=onboarding.get_next_step_description(new_state),
        session_token=session_token,
        expires_in_seconds=settings.user_session_ttl_hours * 3600,
    )


@api_app.post(
    "/v1/auth/request-login-link", response_model=GenericAcceptedResponse, status_code=202
)
@limiter.limit("10/minute")
async def request_login_link(
    request: Request, body: RequestLoginLinkRequest
) -> GenericAcceptedResponse:
    user_store: UserStore = request.app.state.user_store
    ctx = user_store.get_user_by_email(body.email)

    if ctx is not None and ctx.onboarding_status != PENDING_EMAIL_VERIFICATION:
        try:
            token_store: TokenStore = request.app.state.token_store
            raw_token = token_store.issue_user_login_token(ctx.user_id)
            login_url = f"{settings.frontend_base_url}/auth/login?token={raw_token}"
            request.app.state.email_sender.send_login_email(body.email, login_url)
        except Exception as exc:
            logger.warning("Failed to send login email for %s: %s", body.email, exc)

    return GenericAcceptedResponse(message="If an account exists, a sign-in link has been sent.")


@api_app.get("/v1/auth/exchange-login-link", response_model=SessionResponse)
async def exchange_login_link(
    token: str = Query(..., description="Login token from the email link"),
    request: Request = ...,  # type: ignore[assignment]
) -> SessionResponse:
    token_store: TokenStore = request.app.state.token_store
    user_store: UserStore = request.app.state.user_store

    try:
        user_id = token_store.verify_user_login_token(token)
    except TokenNotFoundError:
        raise HTTPException(status_code=400, detail="Invalid login token.")
    except TokenExpiredError:
        raise HTTPException(status_code=400, detail="Login token has expired.")
    except TokenAlreadyUsedError:
        raise HTTPException(status_code=400, detail="Login token has already been used.")

    user = user_store.get_user_row(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if str(user.onboarding_status) == PENDING_EMAIL_VERIFICATION:
        raise HTTPException(
            status_code=409,
            detail="Email must be verified before using a login link.",
        )

    session_token = user_store.issue_user_session(
        user_id,
        ttl_hours=settings.user_session_ttl_hours,
    )
    return SessionResponse(
        user_id=user_id,
        status=str(user.onboarding_status),
        session_token=session_token,
        expires_in_seconds=settings.user_session_ttl_hours * 3600,
    )


@api_app.post("/v1/auth/logout", status_code=204)
async def logout(request: Request, session: AuthedSession) -> Response:
    raw_token = _extract_session_token(request)
    if raw_token:
        request.app.state.user_store.revoke_user_session(raw_token)
    _bust_user_caches(request, session.user_id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Account endpoints (session-authenticated)
# ---------------------------------------------------------------------------


@api_app.get("/v1/account/status", response_model=AccountStatusResponse)
async def account_status(session: AuthedSession, request: Request) -> AccountStatusResponse:
    user_store: UserStore = request.app.state.user_store
    user = user_store.get_user_row(session.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    onboarding_st = str(user.onboarding_status)
    account_st = str(user.account_status)
    return AccountStatusResponse(
        user_id=session.user_id,
        status=onboarding_st,
        account_status=account_st,
        plan_code=str(user.plan_code),
        billing_status=str(user.billing_status),
        next_step=onboarding.get_next_step_description(onboarding_st),
        blockers=_build_blockers(onboarding_st, account_st),
        can_issue_api_key=user_store.user_can_issue_api_keys(session.user_id),
    )


@api_app.put("/v1/account/database", response_model=DatabaseResponse)
async def submit_database(
    body: SubmitDatabaseRequest,
    request: Request,
    session: AuthedSession,
) -> DatabaseResponse:
    user_store: UserStore = request.app.state.user_store
    current_status = user_store.get_user_onboarding_status(session.user_id)

    # Accept both pending_db_connection (first setup) and setup_complete (reconnect)
    if current_status not in (PENDING_DB_CONNECTION, SETUP_COMPLETE):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot submit database: account is in '{current_status}' state.",
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
    user_store.upsert_user_database(
        session.user_id, encrypted_url, name=(body.name or "primary")
    )

    # Activate on first DB submission; on reconnect keep existing status
    if current_status == PENDING_DB_CONNECTION:
        user_store.activate_user(session.user_id)

    _bust_user_caches(request, session.user_id)

    user = user_store.get_user_row(session.user_id)
    plan_code = str(user.plan_code) if user is not None else "free"

    return DatabaseResponse(
        user_id=session.user_id,
        status=SETUP_COMPLETE,
        account_status=ACCOUNT_ACTIVE,
        plan_code=plan_code,
        next_step=onboarding.get_next_step_description(SETUP_COMPLETE),
    )


@api_app.post("/v1/account/api-keys", response_model=CreatedApiKeyResponse, status_code=201)
async def create_api_key(
    body: CreateApiKeyRequest,
    request: Request,
    session: AuthedSession,
) -> CreatedApiKeyResponse:
    allowed_scopes = {"mcp_read", "api_key_admin"}
    bad_scopes = [scope for scope in body.scopes if scope not in allowed_scopes]
    if bad_scopes:
        raise HTTPException(status_code=400, detail=f"Unsupported scopes: {', '.join(bad_scopes)}")

    user_store: UserStore = request.app.state.user_store
    try:
        raw_key, api_key = user_store.create_api_key(
            user_id=session.user_id,
            name=body.name,
            scopes=body.scopes,
        )
    except EntitlementExceededError as exc:
        return _entitlement_conflict_response(exc)
    except StateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    _bust_user_caches(request, session.user_id)
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


@api_app.get("/v1/account/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(request: Request, session: AuthedSession) -> list[ApiKeyResponse]:
    user_store: UserStore = request.app.state.user_store
    rows = user_store.list_api_keys(session.user_id)
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


@api_app.delete("/v1/account/api-keys/{api_key_id}", status_code=204)
async def revoke_api_key(
    api_key_id: str, request: Request, session: AuthedSession
) -> Response:
    user_store: UserStore = request.app.state.user_store
    revoked = user_store.revoke_api_key(session.user_id, api_key_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="API key not found")
    _bust_user_caches(request, session.user_id, api_key_id=api_key_id)
    return Response(status_code=204)


@api_app.post(
    "/v1/account/api-keys/{api_key_id}/rotate", response_model=RotateKeyResponse
)
@limiter.limit("10/hour")
async def rotate_api_key(
    api_key_id: str, request: Request, session: AuthedSession
) -> RotateKeyResponse:
    user_store: UserStore = request.app.state.user_store
    try:
        new_raw_key = user_store.rotate_api_key(session.user_id, api_key_id)
    except EntitlementExceededError as exc:
        return _entitlement_conflict_response(exc)
    except (StateTransitionError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    _bust_user_caches(request, session.user_id, api_key_id=api_key_id)
    return RotateKeyResponse(api_key=new_raw_key)


@api_app.post("/v1/account/setup-payloads", response_model=SetupPayloadResponse)
async def get_setup_payloads(
    body: SetupPayloadRequest,
    request: Request,
    session: AuthedSession,
) -> SetupPayloadResponse:
    user_store: UserStore = request.app.state.user_store
    service = SetupPayloadService(
        user_store,
        app_base_url=settings.app_base_url,
        mcp_auth_mode=settings.mcp_auth_mode,
        oauth_configured=settings.oauth_is_configured(),
        oauth_link_configured=settings.oauth_link_is_configured(),
    )
    try:
        payload = service.build_payload(session.user_id, raw_api_key=body.raw_api_key)
    except LookupError:
        raise HTTPException(status_code=404, detail="User not found")
    except SetupPayloadInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SetupPayloadEligibilityError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return SetupPayloadResponse(
        user_id=payload.user_id,
        status=payload.status,
        account_status=payload.account_status,
        plan_code=payload.plan_code,
        billing_status=payload.billing_status,
        mcp_url=payload.mcp_url,
        mcp_auth_mode=payload.mcp_auth_mode,
        oauth_enabled_for_mcp=payload.oauth_enabled_for_mcp,
        oauth_link_enabled=payload.oauth_link_enabled,
        api_keys_enabled_for_mcp=payload.api_keys_enabled_for_mcp,
        quota_summary=SetupQuotaSummaryResponse(
            daily_limit=payload.quota_summary.daily_limit,
            daily_used=payload.quota_summary.daily_used,
            daily_remaining=payload.quota_summary.daily_remaining,
            reset_at=payload.quota_summary.reset_at.isoformat(),
            warning_level=payload.quota_summary.warning_level,
        ),
        api_key_state=SetupApiKeyStateResponse(
            active_key_count=payload.api_key_state.active_key_count,
            selected_api_key_id=payload.api_key_state.selected_api_key_id,
            selected_api_key_name=payload.api_key_state.selected_api_key_name,
            selected_api_key_prefix=payload.api_key_state.selected_api_key_prefix,
            raw_key_included=payload.api_key_state.raw_key_included,
            requires_manual_key_entry=payload.api_key_state.requires_manual_key_entry,
        ),
        sample_prompts=list(payload.sample_prompts),
        clients=SetupClientsResponse(
            vs_code=_client_setup_response(payload.vs_code),
            cursor=_client_setup_response(payload.cursor),
            chatgpt_developer_mode=_client_setup_response(payload.chatgpt_developer_mode),
            generic_http=_client_setup_response(payload.generic_http),
        ),
    )


@api_app.get("/v1/account/dashboard", response_model=DashboardSummaryResponse)
async def dashboard_summary(
    session: AuthedSession, request: Request
) -> DashboardSummaryResponse:
    user_store: UserStore = request.app.state.user_store
    user = user_store.get_user_row(session.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    plan_code = str(user.plan_code)
    daily_count = int(user.daily_query_count)
    plan = _entitlements.get_plan(plan_code)
    warning_level = _entitlements.quota_warning_level(plan_code, daily_count)

    active_db = user_store.get_active_database(session.user_id)
    api_key_count = user_store.count_active_api_keys(session.user_id)

    return DashboardSummaryResponse(
        user_id=session.user_id,
        account_status=str(user.account_status),
        onboarding_status=str(user.onboarding_status),
        plan_code=plan_code,
        billing_status=str(user.billing_status),
        active_database=(
            ActiveDatabaseSummary(
                name=active_db.name,
                validation_status=active_db.validation_status,
            )
            if active_db is not None
            else None
        ),
        api_key_count=api_key_count,
        quota=QuotaSummary(
            daily_limit=plan.ask_database_per_day,
            daily_used=daily_count,
            daily_remaining=max(0, plan.ask_database_per_day - daily_count),
            reset_at=user.daily_quota_reset_at,
            warning_level=warning_level,
        ),
    )


@api_app.get("/v1/account/usage/recent", response_model=UsageRecentResponse)
async def usage_recent(
    request: Request,
    session: AuthedSession,
    limit: int = Query(default=20, ge=1, le=100),
) -> UsageRecentResponse:
    query_log = request.app.state.query_log
    rows = query_log.get_recent_queries(limit=limit, user_id=session.user_id)
    return UsageRecentResponse(
        items=[
            RecentQueryItem(
                id=int(r["id"]),
                timestamp=str(r["timestamp"]),
                question=str(r["question"]),
                sql=str(r["sql"]) if r["sql"] is not None else None,
                success=bool(r["success"]),
                row_count=int(r["row_count"]) if r["row_count"] is not None else None,
                duration_ms=int(r["duration_ms"]) if r["duration_ms"] is not None else None,
                error=str(r["error"]) if r["error"] is not None else None,
            )
            for r in rows
        ],
        total=len(rows),
    )


# ---------------------------------------------------------------------------
# Account meta (API-key-authenticated)
# ---------------------------------------------------------------------------


@api_app.get("/v1/account", response_model=AccountResponse)
async def get_account(request: Request, session: AuthedSession) -> AccountResponse:
    user_store: UserStore = request.app.state.user_store
    row = user_store.get_user_row(session.user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    account_st = str(row.account_status)
    onboarding_st = str(row.onboarding_status)
    return AccountResponse(
        user_id=str(row.id),
        is_active=account_st == ACCOUNT_ACTIVE and onboarding_st == SETUP_COMPLETE,
        created_at=row.created_at.isoformat(),
        status=onboarding_st,
        account_status=account_st,
        plan_code=str(row.plan_code),
        billing_status=str(row.billing_status),
    )


# ---------------------------------------------------------------------------
# OAuth MCP account-linking endpoints
# ---------------------------------------------------------------------------

_OAUTH_LINK_STATE_TTL_SECONDS = 600


def _oauth_frontend_url(*, linked: bool | None = None, error: str | None = None) -> str:
    base = f"{settings.frontend_base_url.rstrip('/')}/setup/clients"
    if linked:
        return f"{base}?oauth=linked"
    if error:
        return f"{base}?oauth_error={error}"
    return base


def _issue_oauth_link_state(request: Request, *, user_id: str, code_verifier: str) -> str:
    cipher = request.app.state.cipher
    payload = json.dumps({"user_id": user_id, "code_verifier": code_verifier})
    return cipher.encrypt(payload)


def _consume_oauth_link_state(request: Request, *, state: str) -> tuple[str, str] | None:
    cipher = request.app.state.cipher
    try:
        payload = cipher.decrypt_with_ttl(state, _OAUTH_LINK_STATE_TTL_SECONDS)
        data = json.loads(payload)
        user_id = str(data["user_id"])
        code_verifier = str(data["code_verifier"])
    except Exception:
        return None
    return user_id, code_verifier


def _require_oauth_link_configured() -> None:
    if not settings.oauth_link_is_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "OAuth account linking is not configured on this deployment. "
                "Set OAUTH_CLIENT_ID, OAUTH_ISSUER_URL, and OAUTH_LINK_REDIRECT_URI."
            ),
        )


@api_app.get("/v1/account/mcp-oauth/status", response_model=OAuthLinkStatusResponse)
async def oauth_link_status(
    session: AuthedSession, request: Request
) -> OAuthLinkStatusResponse:
    """Return the current OAuth identity linkage status for the authenticated user."""
    user_store: UserStore = request.app.state.user_store
    link_status = user_store.get_oauth_link_status(session.user_id)
    if link_status is None:
        raise HTTPException(status_code=404, detail="User not found")
    return OAuthLinkStatusResponse(
        linked=link_status.linked,
        issuer=link_status.issuer,
        oauth_email=link_status.oauth_email,
        oauth_last_login_at=(
            link_status.oauth_last_login_at.isoformat()
            if link_status.oauth_last_login_at is not None
            else None
        ),
    )


@api_app.post("/v1/account/mcp-oauth/start", response_model=OAuthLinkStartResponse)
@limiter.limit("10/minute")
async def oauth_link_start(
    request: Request, session: AuthedSession
) -> OAuthLinkStartResponse:
    """Start the OAuth account-linking flow.

    Returns an ``authorization_url`` that the frontend should redirect the user
    to.  After the user authenticates with the OAuth provider the provider
    redirects back to the configured callback URL, which calls
    ``oauth_link_callback``.
    """
    _require_oauth_link_configured()

    import base64
    import hashlib
    import os
    from urllib.parse import urlencode

    # Generate PKCE code verifier + challenge
    code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    code_challenge = (
        base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        )
        .rstrip(b"=")
        .decode()
    )

    state = _issue_oauth_link_state(
        request,
        user_id=session.user_id,
        code_verifier=code_verifier,
    )

    # Build the authorization URL
    issuer = settings.oauth_issuer_url.rstrip("/")
    params = {
        "response_type": "code",
        "client_id": settings.oauth_client_id,
        "redirect_uri": settings.oauth_link_redirect_uri,
        "scope": "openid email profile",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    authorization_url = f"{issuer}/authorize?{urlencode(params)}"
    return OAuthLinkStartResponse(authorization_url=authorization_url, state=state)


@api_app.get("/v1/account/mcp-oauth/callback")
@limiter.limit("20/minute")
async def oauth_link_callback(
    request: Request,
    code: str = Query(..., description="Authorization code from the OAuth provider"),
    state: str = Query(..., description="State token matching the start request"),
) -> Response:
    """Handle the OAuth callback after the user authenticates with the provider.

    Exchanges the authorization code for tokens, validates the identity, links
    it to the local account, and redirects the browser to the frontend.
    """
    _require_oauth_link_configured()

    import httpx

    pending = _consume_oauth_link_state(request, state=state)
    if pending is None:
        return Response(
            status_code=302,
            headers={"location": _oauth_frontend_url(error="invalid_state")},
        )

    user_id, code_verifier = pending

    # Exchange code for tokens
    issuer = settings.oauth_issuer_url.rstrip("/")
    token_url = f"{issuer}/oauth/token"
    token_payload: dict = {
        "grant_type": "authorization_code",
        "client_id": settings.oauth_client_id,
        "code": code,
        "redirect_uri": settings.oauth_link_redirect_uri,
        "code_verifier": code_verifier,
    }
    if settings.oauth_client_secret:
        token_payload["client_secret"] = settings.oauth_client_secret

    try:
        async with httpx.AsyncClient(timeout=settings.oauth_http_timeout_seconds) as client:
            resp = await client.post(token_url, data=token_payload)
        resp.raise_for_status()
        token_data = resp.json()
    except Exception as exc:
        logger.warning("OAuth token exchange failed for user %s: %s", user_id, exc)
        return Response(
            status_code=302,
            headers={"location": _oauth_frontend_url(error="token_exchange_failed")},
        )

    # Verify the access token to extract identity
    if not settings.oauth_is_configured():
        return Response(
            status_code=302,
            headers={"location": _oauth_frontend_url(error="oauth_not_configured")},
        )

    from src.auth.oauth_verifier import OAuthVerifier, OAuthVerificationError

    # For linking we only need identity claims (issuer + sub), not resource access.
    # id_token is always a signed JWT; access_token may be opaque when no audience
    # was requested, so prefer id_token here and skip audience verification.
    verifier = OAuthVerifier(
        issuer_url=settings.oauth_issuer_url,
        audience="",  # no audience check — id_token aud is the client_id, not the MCP resource
        required_scopes=[],
        jwks_url=settings.oauth_jwks_url,
        jwks_cache_ttl=settings.oauth_jwks_cache_seconds,
    )

    access_token = token_data.get("id_token") or token_data.get("access_token", "")
    try:
        claims = verifier.verify(access_token)
    except OAuthVerificationError as exc:
        logger.warning("OAuth token verification failed for user %s: %s", user_id, exc)
        return Response(
            status_code=302,
            headers={"location": _oauth_frontend_url(error="token_invalid")},
        )

    from src.auth.user_store import StateTransitionError
    from datetime import UTC, datetime

    user_store: UserStore = request.app.state.user_store
    email_verified_at = datetime.now(UTC) if claims.email_verified else None
    try:
        user_store.link_user_oauth_identity(
            user_id,
            issuer=claims.issuer,
            subject=claims.subject,
            oauth_email=claims.email,
            oauth_email_verified_at=email_verified_at,
        )
    except StateTransitionError as exc:
        logger.warning("OAuth link conflict for user %s: %s", user_id, exc)
        return Response(
            status_code=302,
            headers={"location": _oauth_frontend_url(error="identity_conflict")},
        )

    # Bust caches so the new linkage is picked up immediately
    _bust_user_caches(request, user_id)

    return Response(status_code=302, headers={"location": _oauth_frontend_url(linked=True)})


@api_app.delete("/v1/account/mcp-oauth/link", response_model=OAuthUnlinkResponse)
async def oauth_unlink(
    request: Request, session: AuthedSession
) -> OAuthUnlinkResponse:
    """Remove the OAuth identity binding from the authenticated user's account."""
    user_store: UserStore = request.app.state.user_store
    unlinked = user_store.unlink_oauth_identity(session.user_id)
    if not unlinked:
        raise HTTPException(status_code=404, detail="User not found")
    _bust_user_caches(request, session.user_id)
    return OAuthUnlinkResponse(message="OAuth identity unlinked successfully.")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


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
