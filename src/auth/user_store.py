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
from src.auth.onboarding import ACTIVE, CLOSED, PENDING_REVIEW, SUSPENDED
from src.auth.url_guard import validate_database_url


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String(36), primary_key=True)
    name = Column(String(200), nullable=False)
    status = Column(String(40), nullable=False, default="pending_email_verification", index=True)
    trust_level = Column(String(40), nullable=False, default="unverified")
    billing_status = Column(String(40), nullable=False, default="not_started")
    plan_code = Column(String(40), nullable=False, default="new_trial")
    daily_query_count = Column(Integer, nullable=False, default=0)
    daily_quota_reset_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    suspended_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)


class TenantMembership(Base):
    __tablename__ = "tenant_memberships"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(254), nullable=False, index=True)
    role = Column(String(30), nullable=False, default="owner")
    email_verified_at = Column(DateTime(timezone=True), nullable=True)
    mfa_verified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
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
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
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


class StateTransitionError(Exception):
    """Raised when a state-gated operation is not allowed."""


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
    return (now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))


def _default_tenant_name(email: str) -> str:
    local = email.split("@", 1)[0].strip() or "workspace"
    return f"{local[:60]}'s workspace"


def _normalize_scopes(scopes: str | list[str] | tuple[str, ...] | set[str] | frozenset[str]) -> tuple[str, frozenset[str]]:
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

    # ------------------------------------------------------------------
    # Tenant + owner lifecycle
    # ------------------------------------------------------------------

    def create_tenant_with_owner(self, email: str, tenant_name: str | None = None) -> tuple[str, str]:
        tenant_id = str(uuid.uuid4())
        membership_id = str(uuid.uuid4())
        now = _utcnow()

        tenant = Tenant(
            id=tenant_id,
            name=(tenant_name or _default_tenant_name(email)).strip() or _default_tenant_name(email),
            status="pending_email_verification",
            trust_level="unverified",
            billing_status="not_started",
            plan_code="new_trial",
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
                .filter(Tenant.status != CLOSED)
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
            if tenant.status in (SUSPENDED, CLOSED):
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
        with Session(self._engine) as session:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None:
                return None
            return str(tenant.status)

    def transition_tenant_state(self, tenant_id: str, new_state: str) -> bool:
        now = _utcnow()
        with Session(self._engine) as session:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None:
                return False
            tenant.status = new_state  # type: ignore[assignment]
            tenant.updated_at = now  # type: ignore[assignment]
            if new_state == SUSPENDED:
                tenant.suspended_at = now  # type: ignore[assignment]
            if new_state == CLOSED:
                tenant.closed_at = now  # type: ignore[assignment]
            session.commit()
        return True

    def list_tenants_by_status(self, status: str) -> list[tuple[Tenant, TenantMembership | None]]:
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

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        with Session(self._engine) as session:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None:
                return None
            session.expunge(tenant)
            return tenant

    def owner_can_issue_api_keys(self, tenant_id: str) -> bool:
        status = self.get_tenant_status(tenant_id)
        if status != ACTIVE:
            return False
        return self.get_active_database(tenant_id) is not None

    # ------------------------------------------------------------------
    # Database registration
    # ------------------------------------------------------------------

    def upsert_active_database(self, tenant_id: str, database_url_enc: str, name: str = "primary") -> str:
        now = _utcnow()
        with Session(self._engine) as session:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None:
                raise ValueError(f"Tenant {tenant_id} not found")
            current = (
                session.query(TenantDatabase)
                .filter_by(tenant_id=tenant_id, is_active=True)
                .order_by(TenantDatabase.created_at.desc())
                .first()
            )
            if current is None:
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
        if not self.owner_can_issue_api_keys(tenant_id):
            raise StateTransitionError("Tenant is not eligible to issue API keys.")

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
            if tenant.status != ACTIVE:
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
        except ValueError:
            return False

    def issue_first_api_key(self, user_id: str) -> str:
        status = self.get_tenant_status(user_id)
        if status != PENDING_REVIEW:
            raise StateTransitionError(
                f"Cannot issue API key: tenant is in '{status}' state, expected '{PENDING_REVIEW}'."
            )
        self.transition_tenant_state(user_id, ACTIVE)
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
        except ValueError:
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
        return self.transition_tenant_state(user_id, CLOSED)

    def increment_daily_quota(self, user_id: str) -> int:
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
                    RETURNING daily_query_count
                    """
                ),
                {"now": now, "next_reset": next_reset, "tenant_id": user_id},
            ).fetchone()
            session.commit()

        if row is None:
            raise ValueError(f"Tenant {user_id} not found")
        return int(row[0])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _owner_context_from_rows(self, membership: TenantMembership, tenant: Tenant) -> OwnerSessionContext:
        return OwnerSessionContext(
            tenant_id=str(tenant.id),
            membership_id=str(membership.id),
            email=str(membership.email),
            role=str(membership.role),
            onboarding_status=str(tenant.status),
            is_active=str(tenant.status) == ACTIVE,
            created_at=_ensure_utc(tenant.created_at),
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
        return UserConfig(
            user_id=str(tenant.id),
            database_url=database_url,
            is_active=str(tenant.status) == ACTIVE,
            onboarding_status=str(tenant.status),
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
            is_active=True,
            onboarding_status=str(tenant.status),
            email=None if membership is None else str(membership.email),
            api_key_id=str(api_key.id),
            database_id=database_id,
            scopes=scopes,
            key_name=str(api_key.name),
        )
