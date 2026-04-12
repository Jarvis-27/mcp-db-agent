"""Tenant-backed auth and persistence layer for hosted multi-tenant mode."""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Engine,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Session

from src.auth.crypto import CredentialCipher
from src.auth.onboarding import (
    ACCOUNT_ACTIVE,
    ACCOUNT_CLOSED,
    ACCOUNT_SUSPENDED,
    BILLING_FREE,
    PENDING_REVIEW,
    SETUP_COMPLETE,
)
from src.auth.url_guard import validate_database_url
from src.entitlements.service import EntitlementService


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String(36), primary_key=True)
    name = Column(String(200), nullable=False)
    # Onboarding progress: pending_email_verification | pending_db_connection |
    #                      setup_complete | pending_review
    status = Column(String(40), nullable=False, default="pending_email_verification", index=True)
    # Account health: active | restricted | suspended | closed
    account_status = Column(String(40), nullable=False, default="active", index=True)
    trust_level = Column(String(40), nullable=False, default="unverified")
    billing_status = Column(String(40), nullable=False, default="free")
    plan_code = Column(String(40), nullable=False, default="free")
    daily_query_count = Column(Integer, nullable=False, default=0)
    daily_quota_reset_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    suspended_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)


class TenantMembership(Base):
    __tablename__ = "tenant_memberships"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email = Column(String(254), nullable=False, index=True)
    role = Column(String(30), nullable=False, default="owner")
    email_verified_at = Column(DateTime(timezone=True), nullable=True)
    mfa_verified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String(100), nullable=False)
    prefix = Column(String(16), nullable=False, index=True)
    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    scope = Column(String(200), nullable=False, default="mcp_read")
    created_by_membership_id = Column(
        String(36),
        ForeignKey("tenant_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class TenantDatabase(Base):
    __tablename__ = "tenant_databases"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String(100), nullable=False, default="primary")
    database_url_enc = Column(Text, nullable=False)
    validation_status = Column(String(40), nullable=False, default="validated")
    last_validation_at = Column(DateTime(timezone=True), nullable=True)
    last_validation_error = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class OwnerSession(Base):
    __tablename__ = "owner_sessions"

    id = Column(String(36), primary_key=True)
    tenant_membership_id = Column(
        String(36),
        ForeignKey("tenant_memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class QueryHistory(Base):
    __tablename__ = "query_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    tenant_id = Column(String(36), nullable=False)
    api_key_id = Column(String(36), nullable=True)
    question = Column(Text, nullable=False)
    sql = Column(Text, nullable=False)
    success = Column(Boolean, nullable=False)
    row_count = Column(Integer, nullable=True)
    attempts = Column(Integer, nullable=False)
    duration_ms = Column(Integer, nullable=False)
    error = Column(Text, nullable=True)
    plan_code = Column(String(40), nullable=True)
    daily_count = Column(Integer, nullable=True)
    daily_limit = Column(Integer, nullable=True)
    warning_level = Column(String(20), nullable=True)

    __table_args__ = (Index("ix_query_history_tenant_id_desc", "tenant_id", "id"),)


@dataclass(frozen=True)
class UserConfig:
    """Machine-auth context returned from API key lookup."""

    user_id: str
    database_url: str | None
    is_active: bool
    onboarding_status: str
    email: str | None
    api_key_id: str | None = None
    database_id: str | None = None
    scopes: frozenset[str] = frozenset({"mcp_read"})
    key_name: str | None = None
    account_status: str = ACCOUNT_ACTIVE
    plan_code: str = "free"
    billing_status: str = BILLING_FREE

    @property
    def tenant_id(self) -> str:
        return self.user_id


@dataclass(frozen=True)
class OwnerSessionContext:
    tenant_id: str
    membership_id: str
    email: str
    role: str
    onboarding_status: str
    is_active: bool
    created_at: datetime
    account_status: str = ACCOUNT_ACTIVE
    plan_code: str = "free"
    billing_status: str = BILLING_FREE


class StateTransitionError(Exception):
    """Raised when a state-gated operation is not allowed."""


class EntitlementExceededError(StateTransitionError):
    """Raised when a tenant action would exceed a plan limit."""

    def __init__(
        self,
        detail: str,
        *,
        code: str,
        plan_code: str,
        current: int,
        limit: int,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.plan_code = plan_code
        self.current = current
        self.limit = limit


@dataclass(frozen=True)
class DailyQuotaSnapshot:
    tenant_id: str
    plan_code: str
    daily_count: int
    daily_quota_reset_at: datetime


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _hash_session(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _next_midnight(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)


def _default_tenant_name(email: str) -> str:
    local = email.split("@", 1)[0].strip() or "workspace"
    return f"{local[:60]}'s workspace"


def _normalize_scopes(
    scopes: str | list[str] | tuple[str, ...] | set[str] | frozenset[str],
) -> tuple[str, frozenset[str]]:
    if isinstance(scopes, str):
        parts = [part.strip() for part in scopes.split(",") if part.strip()]
    else:
        parts = [str(part).strip() for part in scopes if str(part).strip()]
    if not parts:
        parts = ["mcp_read"]
    unique = tuple(dict.fromkeys(parts))
    return ",".join(unique), frozenset(unique)


class UserStore:
    """Tenant-backed DAO used by the API layer and MCP auth path."""

    def __init__(self, engine: Engine, cipher: CredentialCipher) -> None:
        self._engine = engine
        self._cipher = cipher
        self._entitlements = EntitlementService()

    # ------------------------------------------------------------------
    # Tenant + owner lifecycle
    # ------------------------------------------------------------------

    def create_tenant_with_owner(
        self, email: str, tenant_name: str | None = None
    ) -> tuple[str, str]:
        tenant_id = str(uuid.uuid4())
        membership_id = str(uuid.uuid4())
        now = _utcnow()

        tenant = Tenant(
            id=tenant_id,
            name=(tenant_name or _default_tenant_name(email)).strip()
            or _default_tenant_name(email),
            status="pending_email_verification",
            account_status=ACCOUNT_ACTIVE,
            trust_level="unverified",
            billing_status=BILLING_FREE,
            plan_code="free",
            daily_query_count=0,
            daily_quota_reset_at=_next_midnight(now),
            created_at=now,
            updated_at=now,
            suspended_at=None,
            closed_at=None,
        )
        membership = TenantMembership(
            id=membership_id,
            tenant_id=tenant_id,
            email=email,
            role="owner",
            email_verified_at=None,
            mfa_verified_at=None,
            created_at=now,
            updated_at=now,
        )

        with Session(self._engine) as session:
            session.add(tenant)
            session.add(membership)
            session.commit()

        return tenant_id, membership_id

    def get_owner_membership_by_email(self, email: str) -> OwnerSessionContext | None:
        with Session(self._engine) as session:
            row = (
                session.query(TenantMembership, Tenant)
                .join(Tenant, TenantMembership.tenant_id == Tenant.id)
                .filter(TenantMembership.email == email)
                .filter(Tenant.account_status != ACCOUNT_CLOSED)
                .order_by(Tenant.created_at.desc())
                .first()
            )
            if row is None:
                return None
            membership, tenant = row
            return self._owner_context_from_rows(membership, tenant)

    def get_owner_membership_by_id(self, membership_id: str) -> OwnerSessionContext | None:
        with Session(self._engine) as session:
            row = (
                session.query(TenantMembership, Tenant)
                .join(Tenant, TenantMembership.tenant_id == Tenant.id)
                .filter(TenantMembership.id == membership_id)
                .first()
            )
            if row is None:
                return None
            membership, tenant = row
            return self._owner_context_from_rows(membership, tenant)

    def set_email_verified(self, membership_id: str) -> bool:
        now = _utcnow()
        with Session(self._engine) as session:
            membership = session.get(TenantMembership, membership_id)
            if membership is None:
                return False
            tenant = session.get(Tenant, membership.tenant_id)
            membership.email_verified_at = now  # type: ignore[assignment]
            membership.updated_at = now  # type: ignore[assignment]
            if tenant is not None:
                tenant.trust_level = "email_verified"  # type: ignore[assignment]
                tenant.updated_at = now  # type: ignore[assignment]
            session.commit()
        return True

    def issue_owner_session(self, membership_id: str, ttl_hours: int = 24) -> str:
        raw_token = "mdbo_" + secrets.token_urlsafe(32)
        now = _utcnow()
        session_hash = _hash_session(raw_token)

        with Session(self._engine) as session:
            owner_session = OwnerSession(
                id=str(uuid.uuid4()),
                tenant_membership_id=membership_id,
                session_hash=session_hash,
                expires_at=now + timedelta(hours=ttl_hours),
                last_used_at=now,
                revoked_at=None,
                created_at=now,
            )
            session.add(owner_session)
            session.commit()

        return raw_token

    def get_owner_by_session(self, raw_token: str) -> OwnerSessionContext | None:
        token_hash = _hash_session(raw_token)
        now = _utcnow()
        with Session(self._engine) as session:
            row = (
                session.query(OwnerSession, TenantMembership, Tenant)
                .join(TenantMembership, OwnerSession.tenant_membership_id == TenantMembership.id)
                .join(Tenant, TenantMembership.tenant_id == Tenant.id)
                .filter(OwnerSession.session_hash == token_hash)
                .first()
            )
            if row is None:
                return None
            owner_session, membership, tenant = row
            if owner_session.revoked_at is not None:
                return None
            if _ensure_utc(owner_session.expires_at) < now:
                return None
            if str(tenant.account_status) in (ACCOUNT_SUSPENDED, ACCOUNT_CLOSED):
                return None
            owner_session.last_used_at = now  # type: ignore[assignment]
            session.commit()
            return self._owner_context_from_rows(membership, tenant)

    def revoke_owner_session(self, raw_token: str) -> bool:
        token_hash = _hash_session(raw_token)
        now = _utcnow()
        with Session(self._engine) as session:
            owner_session = session.query(OwnerSession).filter_by(session_hash=token_hash).first()
            if owner_session is None or owner_session.revoked_at is not None:
                return False
            owner_session.revoked_at = now  # type: ignore[assignment]
            session.commit()
            return True

    def get_tenant_status(self, tenant_id: str) -> str | None:
        """Return the onboarding status (tenants.status) for the given tenant."""
        with Session(self._engine) as session:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None:
                return None
            return str(tenant.status)

    def get_tenant_account_status(self, tenant_id: str) -> str | None:
        """Return the account status (tenants.account_status) for the given tenant."""
        with Session(self._engine) as session:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None:
                return None
            return str(tenant.account_status)

    def transition_tenant_state(self, tenant_id: str, new_onboarding_state: str) -> bool:
        """Update the onboarding progress state (tenants.status)."""
        now = _utcnow()
        with Session(self._engine) as session:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None:
                return False
            tenant.status = new_onboarding_state  # type: ignore[assignment]
            tenant.updated_at = now  # type: ignore[assignment]
            session.commit()
        return True

    def set_account_status(self, tenant_id: str, new_status: str) -> bool:
        """Update the account health state (tenants.account_status).

        Returns False if the tenant is already closed (terminal) or not found.
        """
        now = _utcnow()
        with Session(self._engine) as session:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None:
                return False
            if str(tenant.account_status) == ACCOUNT_CLOSED:
                return False
            tenant.account_status = new_status  # type: ignore[assignment]
            tenant.updated_at = now  # type: ignore[assignment]
            if new_status == ACCOUNT_SUSPENDED:
                tenant.suspended_at = now  # type: ignore[assignment]
            if new_status == ACCOUNT_CLOSED:
                tenant.closed_at = now  # type: ignore[assignment]
            session.commit()
        return True

    def activate_tenant(self, tenant_id: str) -> bool:
        """Mark onboarding complete and activate the free plan.

        Called automatically after successful database submission.
        Sets: onboarding_status=setup_complete, account_status=active,
              billing_status=free, plan_code=free.
        """
        now = _utcnow()
        with Session(self._engine) as session:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None:
                return False
            tenant.status = SETUP_COMPLETE  # type: ignore[assignment]
            tenant.account_status = ACCOUNT_ACTIVE  # type: ignore[assignment]
            tenant.billing_status = BILLING_FREE  # type: ignore[assignment]
            tenant.plan_code = "free"  # type: ignore[assignment]
            tenant.updated_at = now  # type: ignore[assignment]
            session.commit()
        return True

    def list_tenants_by_status(self, status: str) -> list[tuple[Tenant, TenantMembership | None]]:
        """List tenants by onboarding status."""
        with Session(self._engine) as session:
            rows = (
                session.query(Tenant, TenantMembership)
                .outerjoin(
                    TenantMembership,
                    (TenantMembership.tenant_id == Tenant.id) & (TenantMembership.role == "owner"),
                )
                .filter(Tenant.status == status)
                .order_by(Tenant.created_at)
                .all()
            )
            result: list[tuple[Tenant, TenantMembership | None]] = []
            for tenant, membership in rows:
                session.expunge(tenant)
                if membership is not None:
                    session.expunge(membership)
                result.append((tenant, membership))
            return result

    def list_tenants_by_account_status(
        self, account_status: str
    ) -> list[tuple[Tenant, TenantMembership | None]]:
        """List tenants by account status (active/restricted/suspended/closed)."""
        with Session(self._engine) as session:
            rows = (
                session.query(Tenant, TenantMembership)
                .outerjoin(
                    TenantMembership,
                    (TenantMembership.tenant_id == Tenant.id) & (TenantMembership.role == "owner"),
                )
                .filter(Tenant.account_status == account_status)
                .order_by(Tenant.created_at)
                .all()
            )
            result: list[tuple[Tenant, TenantMembership | None]] = []
            for tenant, membership in rows:
                session.expunge(tenant)
                if membership is not None:
                    session.expunge(membership)
                result.append((tenant, membership))
            return result

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        with Session(self._engine) as session:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None:
                return None
            session.expunge(tenant)
            return tenant

    def count_active_api_keys(self, tenant_id: str) -> int:
        """Return the number of non-revoked API keys for the tenant."""
        with Session(self._engine) as session:
            return (
                session.query(ApiKey)
                .filter(ApiKey.tenant_id == tenant_id, ApiKey.revoked_at.is_(None))
                .count()
            )

    def count_active_databases(self, tenant_id: str) -> int:
        """Return the number of active databases for the tenant."""
        with Session(self._engine) as session:
            return (
                session.query(TenantDatabase)
                .filter(TenantDatabase.tenant_id == tenant_id, TenantDatabase.is_active.is_(True))
                .count()
            )

    def _lock_tenant_for_plan_mutation(self, session: Session, tenant_id: str) -> Tenant | None:
        """Lock the tenant row so plan-limited mutations serialize per tenant."""
        if session.bind is None:
            raise RuntimeError("Session is not bound to an engine")
        if session.bind.dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
            return session.get(Tenant, tenant_id)
        return session.query(Tenant).filter(Tenant.id == tenant_id).with_for_update().first()

    def owner_can_issue_api_keys(self, tenant_id: str) -> bool:
        """True if the tenant has completed setup, account is active, and has a DB."""
        tenant = self.get_tenant(tenant_id)
        if tenant is None:
            return False
        if str(tenant.account_status) != ACCOUNT_ACTIVE:
            return False
        if str(tenant.status) != SETUP_COMPLETE:
            return False
        return self.get_active_database(tenant_id) is not None

    # ------------------------------------------------------------------
    # Database registration
    # ------------------------------------------------------------------

    def upsert_active_database(
        self, tenant_id: str, database_url_enc: str, name: str = "primary"
    ) -> str:
        now = _utcnow()
        with Session(self._engine) as session:
            tenant = self._lock_tenant_for_plan_mutation(session, tenant_id)
            if tenant is None:
                raise ValueError(f"Tenant {tenant_id} not found")
            current = (
                session.query(TenantDatabase)
                .filter_by(tenant_id=tenant_id, is_active=True)
                .order_by(TenantDatabase.created_at.desc())
                .first()
            )
            if current is None:
                active_count = (
                    session.query(TenantDatabase)
                    .filter(
                        TenantDatabase.tenant_id == tenant_id,
                        TenantDatabase.is_active.is_(True),
                    )
                    .count()
                )
                entitlement = self._entitlements.check_database_quota(
                    str(tenant.plan_code),
                    active_count,
                )
                if not entitlement.allowed:
                    raise EntitlementExceededError(
                        "Active database limit reached for your plan.",
                        code=entitlement.reason or "database_limit_reached",
                        plan_code=entitlement.plan_code,
                        current=entitlement.current,
                        limit=entitlement.limit,
                    )
                current = TenantDatabase(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    name=name,
                    database_url_enc=database_url_enc,
                    validation_status="validated",
                    last_validation_at=now,
                    last_validation_error=None,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                session.add(current)
            else:
                current.name = name  # type: ignore[assignment]
                current.database_url_enc = database_url_enc  # type: ignore[assignment]
                current.validation_status = "validated"  # type: ignore[assignment]
                current.last_validation_at = now  # type: ignore[assignment]
                current.last_validation_error = None  # type: ignore[assignment]
                current.is_active = True  # type: ignore[assignment]
                current.updated_at = now  # type: ignore[assignment]
            tenant.updated_at = now  # type: ignore[assignment]
            session.commit()
            return str(current.id)

    def get_active_database(self, tenant_id: str) -> TenantDatabase | None:
        with Session(self._engine) as session:
            db = (
                session.query(TenantDatabase)
                .filter_by(tenant_id=tenant_id, is_active=True)
                .order_by(TenantDatabase.created_at.desc())
                .first()
            )
            if db is None:
                return None
            session.expunge(db)
            return db

    # ------------------------------------------------------------------
    # Machine API key lifecycle
    # ------------------------------------------------------------------

    def create_api_key(
        self,
        tenant_id: str,
        name: str,
        scopes: str | list[str] | tuple[str, ...] | set[str] | frozenset[str],
        created_by_membership_id: str | None,
    ) -> tuple[str, ApiKey]:
        raw_key = "mdbk_" + secrets.token_urlsafe(32)
        now = _utcnow()
        scope_text, _ = _normalize_scopes(scopes)
        api_key = ApiKey(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name=name.strip() or "default",
            prefix=raw_key[:12],
            key_hash=_hash_key(raw_key),
            scope=scope_text,
            created_by_membership_id=created_by_membership_id,
            last_used_at=None,
            revoked_at=None,
            created_at=now,
        )
        with Session(self._engine) as session:
            tenant = self._lock_tenant_for_plan_mutation(session, tenant_id)
            if tenant is None:
                raise ValueError(f"Tenant {tenant_id} not found")
            if str(tenant.account_status) != ACCOUNT_ACTIVE:
                raise StateTransitionError("Tenant is not eligible to issue API keys.")
            if str(tenant.status) != SETUP_COMPLETE:
                raise StateTransitionError("Tenant is not eligible to issue API keys.")
            has_active_db = (
                session.query(TenantDatabase.id)
                .filter(TenantDatabase.tenant_id == tenant_id, TenantDatabase.is_active.is_(True))
                .first()
                is not None
            )
            if not has_active_db:
                raise StateTransitionError("Tenant is not eligible to issue API keys.")

            active_count = (
                session.query(ApiKey)
                .filter(ApiKey.tenant_id == tenant_id, ApiKey.revoked_at.is_(None))
                .count()
            )
            entitlement = self._entitlements.check_api_key_quota(
                str(tenant.plan_code),
                active_count,
            )
            if not entitlement.allowed:
                plan = self._entitlements.get_plan(entitlement.plan_code)
                raise EntitlementExceededError(
                    f"API key limit reached for your plan "
                    f"({plan.max_api_keys} key(s) allowed on the {plan.display_name} plan).",
                    code=entitlement.reason or "api_key_limit_reached",
                    plan_code=entitlement.plan_code,
                    current=entitlement.current,
                    limit=entitlement.limit,
                )
            session.add(api_key)
            session.commit()
            session.refresh(api_key)
            session.expunge(api_key)
        return raw_key, api_key

    def list_api_keys(self, tenant_id: str) -> list[ApiKey]:
        with Session(self._engine) as session:
            rows = (
                session.query(ApiKey)
                .filter(ApiKey.tenant_id == tenant_id)
                .order_by(ApiKey.created_at.desc())
                .all()
            )
            for row in rows:
                session.expunge(row)
            return rows

    def revoke_api_key(self, tenant_id: str, api_key_id: str) -> bool:
        now = _utcnow()
        with Session(self._engine) as session:
            api_key = session.get(ApiKey, api_key_id)
            if api_key is None or str(api_key.tenant_id) != tenant_id:
                return False
            if api_key.revoked_at is not None:
                return False
            api_key.revoked_at = now  # type: ignore[assignment]
            session.commit()
            return True

    def rotate_api_key(self, tenant_id: str, api_key_id: str) -> str:
        with Session(self._engine) as session:
            current = session.get(ApiKey, api_key_id)
            if current is None or str(current.tenant_id) != tenant_id:
                raise ValueError(f"API key {api_key_id} not found")
            if current.revoked_at is not None:
                raise StateTransitionError("Cannot rotate a revoked API key.")
            raw_key = "mdbk_" + secrets.token_urlsafe(32)
            now = _utcnow()
            # Rotation is a replacement, not a net-new key creation, so it does
            # not consume an extra plan slot.
            replacement = ApiKey(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                name=str(current.name),
                prefix=raw_key[:12],
                key_hash=_hash_key(raw_key),
                scope=str(current.scope),
                created_by_membership_id=current.created_by_membership_id,
                last_used_at=None,
                revoked_at=None,
                created_at=now,
            )
            current.revoked_at = now  # type: ignore[assignment]
            session.add(replacement)
            session.commit()
            return raw_key

    def get_user_by_api_key(self, raw_key: str) -> UserConfig | None:
        key_hash = _hash_key(raw_key)
        now = _utcnow()
        with Session(self._engine) as session:
            row = (
                session.query(ApiKey, Tenant, TenantDatabase, TenantMembership)
                .join(Tenant, ApiKey.tenant_id == Tenant.id)
                .outerjoin(
                    TenantDatabase,
                    (TenantDatabase.tenant_id == Tenant.id) & (TenantDatabase.is_active.is_(True)),
                )
                .outerjoin(
                    TenantMembership,
                    (TenantMembership.tenant_id == Tenant.id) & (TenantMembership.role == "owner"),
                )
                .filter(ApiKey.key_hash == key_hash)
                .first()
            )
            if row is None:
                return None
            api_key, tenant, tenant_db, membership = row
            if api_key.revoked_at is not None:
                return None
            # Require both account active AND setup complete.
            if str(tenant.account_status) != ACCOUNT_ACTIVE:
                return None
            if str(tenant.status) != SETUP_COMPLETE:
                return None
            api_key.last_used_at = now  # type: ignore[assignment]
            session.commit()
            return self._api_context_from_rows(api_key, tenant, tenant_db, membership)

    def get_api_key_metadata(self, api_key_id: str) -> ApiKey | None:
        with Session(self._engine) as session:
            api_key = session.get(ApiKey, api_key_id)
            if api_key is None:
                return None
            session.expunge(api_key)
            return api_key

    def get_active_api_key_for_tenant_by_raw_key(
        self, tenant_id: str, raw_key: str
    ) -> ApiKey | None:
        """Return active API key metadata when the raw key belongs to the tenant."""
        key_hash = _hash_key(raw_key)
        with Session(self._engine) as session:
            api_key = (
                session.query(ApiKey)
                .filter(
                    ApiKey.tenant_id == tenant_id,
                    ApiKey.key_hash == key_hash,
                    ApiKey.revoked_at.is_(None),
                )
                .first()
            )
            if api_key is None:
                return None
            session.expunge(api_key)
            return api_key

    # ------------------------------------------------------------------
    # Legacy compatibility helpers used by the bridge release
    # ------------------------------------------------------------------

    def create_user(self, email: str) -> str:
        tenant_id, _membership_id = self.create_tenant_with_owner(email=email)
        return tenant_id

    def get_onboarding_status(self, user_id: str) -> str | None:
        return self.get_tenant_status(user_id)

    def transition_state(self, user_id: str, new_state: str) -> bool:
        return self.transition_tenant_state(user_id, new_state)

    def set_database_url(self, user_id: str, database_url_enc: str) -> bool:
        try:
            self.upsert_active_database(user_id, database_url_enc)
            return True
        except (EntitlementExceededError, ValueError):
            return False

    def issue_first_api_key(self, user_id: str) -> str:
        """Legacy helper: activate tenant and issue the first API key.

        Accepts tenants in setup_complete or pending_review onboarding state.
        """
        status = self.get_tenant_status(user_id)
        if status not in (SETUP_COMPLETE, PENDING_REVIEW):
            raise StateTransitionError(
                f"Cannot issue API key: tenant onboarding state is '{status}'."
            )
        if status == PENDING_REVIEW:
            self.transition_tenant_state(user_id, SETUP_COMPLETE)
        self.set_account_status(user_id, ACCOUNT_ACTIVE)
        raw_key, _api_key = self.create_api_key(
            tenant_id=user_id,
            name="default",
            scopes=["mcp_read"],
            created_by_membership_id=None,
        )
        return raw_key

    def update_user(self, user_id: str, *, database_url: str | None = None) -> bool:
        if database_url is None:
            return self.get_tenant(user_id) is not None
        sanitized_url = validate_database_url(database_url)
        sanitized_url_str = sanitized_url.render_as_string(hide_password=False)
        encrypted = self._cipher.encrypt(sanitized_url_str)
        try:
            self.upsert_active_database(user_id, encrypted)
            return True
        except (EntitlementExceededError, ValueError):
            return False

    def get_user_by_id(self, user_id: str) -> UserConfig | None:
        with Session(self._engine) as session:
            row = (
                session.query(Tenant, TenantDatabase, TenantMembership)
                .outerjoin(
                    TenantDatabase,
                    (TenantDatabase.tenant_id == Tenant.id) & (TenantDatabase.is_active.is_(True)),
                )
                .outerjoin(
                    TenantMembership,
                    (TenantMembership.tenant_id == Tenant.id) & (TenantMembership.role == "owner"),
                )
                .filter(Tenant.id == user_id)
                .first()
            )
            if row is None:
                return None
            tenant, tenant_db, membership = row
            return self._tenant_context_from_rows(tenant, tenant_db, membership)

    def deactivate_user(self, user_id: str) -> bool:
        return self.set_account_status(user_id, ACCOUNT_CLOSED)

    def increment_daily_quota(self, user_id: str) -> int:
        return self.consume_daily_query_quota(user_id).daily_count

    def consume_daily_query_quota(self, user_id: str) -> DailyQuotaSnapshot:
        now = _utcnow()
        next_reset = _next_midnight(now)

        with Session(self._engine) as session:
            row = session.execute(
                text(
                    """
                    UPDATE tenants
                    SET
                        daily_query_count = CASE
                            WHEN :now >= daily_quota_reset_at THEN 1
                            ELSE daily_query_count + 1
                        END,
                        daily_quota_reset_at = CASE
                            WHEN :now >= daily_quota_reset_at THEN :next_reset
                            ELSE daily_quota_reset_at
                        END,
                        updated_at = :now
                    WHERE id = :tenant_id
                    RETURNING plan_code, daily_query_count, daily_quota_reset_at
                    """
                ),
                {"now": now, "next_reset": next_reset, "tenant_id": user_id},
            ).fetchone()
            session.commit()

        if row is None:
            raise ValueError(f"Tenant {user_id} not found")
        reset_at = row[2]
        if isinstance(reset_at, str):
            reset_at = datetime.fromisoformat(reset_at)
        return DailyQuotaSnapshot(
            tenant_id=user_id,
            plan_code=str(row[0]),
            daily_count=int(row[1]),
            daily_quota_reset_at=_ensure_utc(reset_at),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _owner_context_from_rows(
        self, membership: TenantMembership, tenant: Tenant
    ) -> OwnerSessionContext:
        onboarding_status = str(tenant.status)
        account_status = str(tenant.account_status)
        is_active = account_status == ACCOUNT_ACTIVE and onboarding_status == SETUP_COMPLETE
        return OwnerSessionContext(
            tenant_id=str(tenant.id),
            membership_id=str(membership.id),
            email=str(membership.email),
            role=str(membership.role),
            onboarding_status=onboarding_status,
            account_status=account_status,
            is_active=is_active,
            created_at=_ensure_utc(tenant.created_at),
            plan_code=str(tenant.plan_code),
            billing_status=str(tenant.billing_status),
        )

    def _tenant_context_from_rows(
        self,
        tenant: Tenant,
        tenant_db: TenantDatabase | None,
        membership: TenantMembership | None,
    ) -> UserConfig:
        database_url = None
        if tenant_db is not None:
            database_url = self._cipher.decrypt(str(tenant_db.database_url_enc))
        onboarding_status = str(tenant.status)
        account_status = str(tenant.account_status)
        is_active = account_status == ACCOUNT_ACTIVE and onboarding_status == SETUP_COMPLETE
        return UserConfig(
            user_id=str(tenant.id),
            database_url=database_url,
            is_active=is_active,
            onboarding_status=onboarding_status,
            account_status=account_status,
            plan_code=str(tenant.plan_code),
            billing_status=str(tenant.billing_status),
            email=None if membership is None else str(membership.email),
            api_key_id=None,
            database_id=None if tenant_db is None else str(tenant_db.id),
            scopes=frozenset({"mcp_read"}),
            key_name=None,
        )

    def _api_context_from_rows(
        self,
        api_key: ApiKey,
        tenant: Tenant,
        tenant_db: TenantDatabase | None,
        membership: TenantMembership | None,
    ) -> UserConfig:
        database_url = None
        database_id = None
        if tenant_db is not None:
            database_url = self._cipher.decrypt(str(tenant_db.database_url_enc))
            database_id = str(tenant_db.id)
        _scope_text, scopes = _normalize_scopes(str(api_key.scope))
        return UserConfig(
            user_id=str(tenant.id),
            database_url=database_url,
            is_active=True,  # already verified account_status==active AND status==setup_complete
            onboarding_status=str(tenant.status),
            account_status=str(tenant.account_status),
            plan_code=str(tenant.plan_code),
            billing_status=str(tenant.billing_status),
            email=None if membership is None else str(membership.email),
            api_key_id=str(api_key.id),
            database_id=database_id,
            scopes=scopes,
            key_name=str(api_key.name),
        )
