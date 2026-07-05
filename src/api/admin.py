"""Operator-only admin endpoints.

Mounted under ``/v1/admin``. Gated by the session cookie path
(``require_user_session``) plus an env-only email allowlist
(``settings.admin_emails``). When ``ADMIN_EMAILS`` is empty every endpoint
returns 403 — a deliberate safe default.

Mutation endpoints emit ``logger.info("admin_action", ...)`` as a minimal
audit trail; a persistent ``admin_audit_log`` table is a planned v2 item.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from src.api.app import (
    _bust_user_caches,
    _scopes_for_response,
    require_user_session,
)
from src.api.schemas import (
    AdminApiKeySummary,
    AdminGrant,
    AdminMeResponse,
    AdminOverviewResponse,
    AdminQueryDailyCount,
    AdminQueryListItem,
    AdminQueryListResponse,
    AdminSuspendRequest,
    AdminUserActionResponse,
    AdminUserCountsByStatus,
    AdminUserDetailResponse,
    AdminUserListItem,
    AdminUsersListResponse,
    RecentQueryItem,
)
from src.auth.onboarding import ACCOUNT_ACTIVE, ACCOUNT_CLOSED, ACCOUNT_SUSPENDED
from src.auth.user_store import UserSessionContext, UserStore
from src.config import settings
from src.core.query_log import QueryLog

import logging

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/v1/admin", tags=["admin"])


# ----------------------------------------------------------------------
# Auth gate
# ----------------------------------------------------------------------


def require_admin(
    session: Annotated[UserSessionContext, Depends(require_user_session)],
) -> UserSessionContext:
    allowed = settings.admin_emails_set()
    if not session.email or session.email.lower() not in allowed:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return session


AuthedAdmin = Annotated[UserSessionContext, Depends(require_admin)]


def _iso(dt: Any) -> str | None:
    # Accepts datetime | None | sqlalchemy Column[datetime] (latter resolves to
    # datetime at runtime on instance access). Annotated as Any so mypy does
    # not complain about Column[datetime] vs datetime | None.
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def _audit(action: str, *, actor: str, target: str | None = None, **extra: object) -> None:
    payload: dict[str, object] = {"action": action, "actor": actor}
    if target:
        payload["target"] = target
    payload.update(extra)
    logger.info("admin_action", extra=payload)


def _recent_query_item(r: dict[str, Any]) -> RecentQueryItem:
    return RecentQueryItem(
        id=int(r["id"]),
        timestamp=str(r["timestamp"]),
        created_at=str(r["timestamp"]),
        question=str(r["question"]),
        sql=str(r["sql"]) if r["sql"] is not None else None,
        success=bool(r["success"]),
        row_count=int(r["row_count"]) if r["row_count"] is not None else None,
        duration_ms=int(r["duration_ms"]) if r["duration_ms"] is not None else None,
        error=str(r["error"]) if r["error"] is not None else None,
        attempts=int(r["attempts"]),
        warning_level=str(r["warning_level"]) if r["warning_level"] is not None else None,
        api_key_id=str(r["api_key_id"]) if r["api_key_id"] is not None else None,
        api_key_name=None,
    )


def _admin_query_item(r: dict[str, Any]) -> AdminQueryListItem:
    return AdminQueryListItem(
        id=int(r["id"]),
        timestamp=str(r["timestamp"]),
        user_id=str(r["user_id"]),
        user_email=str(r["user_email"]) if r["user_email"] is not None else None,
        api_key_id=str(r["api_key_id"]) if r["api_key_id"] is not None else None,
        question=str(r["question"]),
        sql=str(r["sql"]) if r["sql"] is not None else None,
        success=bool(r["success"]),
        row_count=int(r["row_count"]) if r["row_count"] is not None else None,
        duration_ms=int(r["duration_ms"]) if r["duration_ms"] is not None else None,
        error=str(r["error"]) if r["error"] is not None else None,
        error_code=str(r["error_code"]) if r["error_code"] is not None else None,
        attempts=int(r["attempts"]),
    )


# ----------------------------------------------------------------------
# /me
# ----------------------------------------------------------------------


@router.get("/me", response_model=AdminMeResponse)
async def admin_me(admin: AuthedAdmin) -> AdminMeResponse:
    return AdminMeResponse(
        user_id=admin.user_id,
        email=admin.email,
        is_admin=True,
        grants=[AdminGrant(scope="operator")],
    )


# ----------------------------------------------------------------------
# /overview
# ----------------------------------------------------------------------


@router.get("/overview", response_model=AdminOverviewResponse)
async def admin_overview(request: Request, admin: AuthedAdmin) -> AdminOverviewResponse:
    user_store: UserStore = request.app.state.user_store
    query_log: QueryLog = request.app.state.query_log

    status_counts = user_store.count_users_by_status()
    users_by_status = AdminUserCountsByStatus(
        active=status_counts.get(ACCOUNT_ACTIVE, 0),
        suspended=status_counts.get(ACCOUNT_SUSPENDED, 0),
        closed=status_counts.get(ACCOUNT_CLOSED, 0),
        pending_email_verification=status_counts.get("pending_email_verification", 0),
    )
    users_total = users_by_status.active + users_by_status.suspended + users_by_status.closed
    since_7d = datetime.now(UTC) - timedelta(days=7)
    users_active_7d = user_store.count_users_active_in_window(since_7d)

    stats = query_log.get_aggregate_stats_today()
    error_rate = (stats.errors / stats.total) if stats.total else 0.0

    daily = query_log.get_daily_counts(days=14)
    return AdminOverviewResponse(
        users_total=users_total,
        users_active_7d=users_active_7d,
        users_by_status=users_by_status,
        queries_today=stats.total,
        error_rate_today=round(error_rate, 4),
        p50_duration_ms_today=stats.p50_duration_ms,
        p95_duration_ms_today=stats.p95_duration_ms,
        daily_query_counts=[
            AdminQueryDailyCount(date=d.date, total=d.total, errors=d.errors) for d in daily
        ],
    )


# ----------------------------------------------------------------------
# /users — list
# ----------------------------------------------------------------------


@router.get("/users", response_model=AdminUsersListResponse)
async def admin_list_users(
    request: Request,
    admin: AuthedAdmin,
    q: str | None = Query(default=None, max_length=254),
    status: str | None = Query(default=None, max_length=40),
    plan: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> AdminUsersListResponse:
    user_store: UserStore = request.app.state.user_store
    items, total = user_store.list_users(q=q, status=status, plan=plan, limit=limit, offset=offset)
    return AdminUsersListResponse(
        items=[
            AdminUserListItem(
                user_id=row.user_id,
                email=row.email,
                plan_code=row.plan_code,
                account_status=row.account_status,
                onboarding_status=row.onboarding_status,
                daily_query_count=row.daily_query_count,
                daily_quota_reset_at=row.daily_quota_reset_at.isoformat(),
                created_at=row.created_at.isoformat(),
                last_query_at=_iso(row.last_query_at),
            )
            for row in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


# ----------------------------------------------------------------------
# /users/{user_id} — detail
# ----------------------------------------------------------------------


@router.get("/users/{user_id}", response_model=AdminUserDetailResponse)
async def admin_user_detail(
    user_id: str, request: Request, admin: AuthedAdmin
) -> AdminUserDetailResponse:
    user_store: UserStore = request.app.state.user_store
    query_log: QueryLog = request.app.state.query_log

    user = user_store.get_user_row(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    api_keys = user_store.get_active_api_keys_for_admin(user_id)
    recent = query_log.get_recent_queries(limit=20, user_id=user_id)

    return AdminUserDetailResponse(
        user_id=str(user.id),
        email=str(user.email),
        plan_code=str(user.plan_code),
        billing_status=str(user.billing_status),
        account_status=str(user.account_status),
        onboarding_status=str(user.onboarding_status),
        timezone=str(user.timezone or "UTC"),
        created_at=user.created_at.isoformat() if user.created_at is not None else "",
        updated_at=user.updated_at.isoformat() if user.updated_at is not None else "",
        email_verified_at=_iso(user.email_verified_at),
        suspended_at=_iso(user.suspended_at),
        closed_at=_iso(user.closed_at),
        db_name=str(user.db_name) if user.db_name is not None else None,
        db_validation_status=(
            str(user.db_validation_status) if user.db_validation_status is not None else None
        ),
        db_last_validation_at=_iso(user.db_last_validation_at),
        daily_query_count=int(user.daily_query_count or 0),
        daily_quota_reset_at=(
            user.daily_quota_reset_at.isoformat() if user.daily_quota_reset_at is not None else ""
        ),
        api_keys=[
            AdminApiKeySummary(
                id=str(k.id),
                name=str(k.name),
                prefix=str(k.prefix),
                scopes=_scopes_for_response(str(k.scope)),
                created_at=k.created_at.isoformat() if k.created_at is not None else "",
                last_used_at=_iso(k.last_used_at),
                revoked_at=_iso(k.revoked_at),
            )
            for k in api_keys
        ],
        recent_queries=[_recent_query_item(cast(dict[str, Any], r)) for r in recent],
    )


# ----------------------------------------------------------------------
# /users/{user_id}/suspend | /unsuspend | /close
# ----------------------------------------------------------------------


def _action_response(user) -> AdminUserActionResponse:
    return AdminUserActionResponse(
        user_id=str(user.id),
        account_status=str(user.account_status),
        suspended_at=_iso(user.suspended_at),
        closed_at=_iso(user.closed_at),
    )


@router.post("/users/{user_id}/suspend", response_model=AdminUserActionResponse)
async def admin_suspend_user(
    user_id: str,
    body: AdminSuspendRequest,
    request: Request,
    admin: AuthedAdmin,
) -> AdminUserActionResponse:
    user_store: UserStore = request.app.state.user_store
    current = user_store.get_user_row(user_id)
    if current is None:
        raise HTTPException(status_code=404, detail="User not found")
    if str(current.account_status) == ACCOUNT_CLOSED:
        raise HTTPException(status_code=409, detail="Account is closed and cannot be suspended.")
    if str(current.account_status) == ACCOUNT_SUSPENDED:
        raise HTTPException(status_code=409, detail="Account is already suspended.")

    ok = user_store.set_account_status(user_id, ACCOUNT_SUSPENDED)
    if not ok:
        raise HTTPException(status_code=409, detail="Could not suspend user.")
    _bust_user_caches(request, user_id)
    _audit("suspend_user", actor=admin.email, target=user_id, reason=body.reason)

    refreshed = user_store.get_user_row(user_id)
    if refreshed is None:
        raise HTTPException(status_code=404, detail="User disappeared mid-request")
    return _action_response(refreshed)


@router.post("/users/{user_id}/unsuspend", response_model=AdminUserActionResponse)
async def admin_unsuspend_user(
    user_id: str, request: Request, admin: AuthedAdmin
) -> AdminUserActionResponse:
    user_store: UserStore = request.app.state.user_store
    current = user_store.get_user_row(user_id)
    if current is None:
        raise HTTPException(status_code=404, detail="User not found")
    if str(current.account_status) == ACCOUNT_CLOSED:
        raise HTTPException(status_code=409, detail="Account is closed.")
    if str(current.account_status) != ACCOUNT_SUSPENDED:
        raise HTTPException(status_code=409, detail="Account is not suspended.")

    ok = user_store.set_account_status(user_id, ACCOUNT_ACTIVE)
    if not ok:
        raise HTTPException(status_code=409, detail="Could not unsuspend user.")
    _bust_user_caches(request, user_id)
    _audit("unsuspend_user", actor=admin.email, target=user_id)

    refreshed = user_store.get_user_row(user_id)
    if refreshed is None:
        raise HTTPException(status_code=404, detail="User disappeared mid-request")
    return _action_response(refreshed)


@router.post("/users/{user_id}/close", response_model=AdminUserActionResponse)
async def admin_close_user(
    user_id: str, request: Request, admin: AuthedAdmin
) -> AdminUserActionResponse:
    user_store: UserStore = request.app.state.user_store
    current = user_store.get_user_row(user_id)
    if current is None:
        raise HTTPException(status_code=404, detail="User not found")
    if str(current.account_status) == ACCOUNT_CLOSED:
        raise HTTPException(status_code=409, detail="Account is already closed.")

    ok = user_store.set_account_status(user_id, ACCOUNT_CLOSED)
    if not ok:
        raise HTTPException(status_code=409, detail="Could not close user.")

    keys_revoked = user_store.revoke_all_user_api_keys(user_id)
    sessions_revoked = user_store.revoke_all_user_sessions(user_id)
    _bust_user_caches(request, user_id)
    _audit(
        "close_user",
        actor=admin.email,
        target=user_id,
        keys_revoked=keys_revoked,
        sessions_revoked=sessions_revoked,
    )

    refreshed = user_store.get_user_row(user_id)
    if refreshed is None:
        raise HTTPException(status_code=404, detail="User disappeared mid-request")
    return _action_response(refreshed)


# ----------------------------------------------------------------------
# /users/{user_id}/api-keys/{api_key_id}/revoke
# ----------------------------------------------------------------------


@router.post(
    "/users/{user_id}/api-keys/{api_key_id}/revoke",
    status_code=204,
    response_class=Response,
)
async def admin_revoke_api_key(
    user_id: str,
    api_key_id: str,
    request: Request,
    admin: AuthedAdmin,
) -> Response:
    user_store: UserStore = request.app.state.user_store
    if user_store.get_user_row(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")

    ok = user_store.revoke_api_key(user_id, api_key_id)
    if not ok:
        raise HTTPException(status_code=404, detail="API key not found or already revoked")

    _bust_user_caches(request, user_id, api_key_id=api_key_id)
    _audit("revoke_api_key", actor=admin.email, target=user_id, api_key_id=api_key_id)
    return Response(status_code=204)


# ----------------------------------------------------------------------
# /queries — cross-user listing
# ----------------------------------------------------------------------


@router.get("/queries", response_model=AdminQueryListResponse)
async def admin_list_queries(
    request: Request,
    admin: AuthedAdmin,
    user_id: str | None = Query(default=None, max_length=64),
    success: bool | None = Query(default=None),
    error_code: str | None = Query(default=None, max_length=40),
    since: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> AdminQueryListResponse:
    query_log: QueryLog = request.app.state.query_log

    since_dt: datetime | None = None
    if since:
        try:
            parsed = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid 'since' timestamp")
        since_dt = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)

    items, total = query_log.list_queries_admin(
        user_id=user_id,
        success=success,
        error_code=error_code,
        since=since_dt,
        limit=limit,
        offset=offset,
    )
    return AdminQueryListResponse(
        items=[_admin_query_item(cast(dict[str, Any], r)) for r in items],
        total=total,
        limit=limit,
        offset=offset,
    )
