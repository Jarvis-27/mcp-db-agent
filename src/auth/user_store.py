"""Single-user-account persistence layer for the hosted HTTP product.

Each row in `users` represents one account — identity, onboarding state,
account state, billing state, quota counters, and the single connected
database are all inlined.  The legacy Tenant / TenantMembership / TenantDatabase /
OwnerSession tables are replaced by User / UserSession.
"""

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
    SETUP_COMPLETE,
)
from src.entitlements.service import EntitlementService


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    email = Column(String(254), nullable=False, unique=True, index=True)
    email_verified_at = Column(DateTime(timezone=True), nullable=True)
    # Onboarding progress: pending_email_verification | pending_db_connection | setup_complete
    onboarding_status = Column(
        String(40), nullable=False, default="pending_email_verification", index=True
    )
    # Account health: active | suspended | closed
    account_status = Column(String(40), nullable=False, default="active", index=True)
    billing_status = Column(String(40), nullable=False, default="free")
    plan_code = Column(String(40), nullable=False, default="free")
    daily_query_count = Column(Integer, nullable=False, default=0)
    daily_quota_reset_at = Column(DateTime(timezone=True), nullable=False)
    # Inlined active database (nullable until submitted)
    db_url_enc = Column(Text, nullable=True)
    db_name = Column(String(100), nullable=True)
    db_validation_status = Column(String(40), nullable=True)
    db_last_validation_at = Column(DateTime(timezone=True), nullable=True)
    db_last_validation_error = Column(Text, nullable=True)
    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    suspended_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(String(36), primary_key=True)
    user_id = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(String(36), primary_key=True)
    user_id = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String(100), nullable=False)
    prefix = Column(String(16), nullable=False, index=True)
    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    scope = Column(String(200), nullable=False, default="mcp_read")
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class QueryHistory(Base):
    __tablename__ = "query_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    user_id = Column(String(36), nullable=False)
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

    __table_args__ = (Index("ix_query_history_user_id_desc", "user_id", "id"),)


# ---------------------------------------------------------------------------
# In-memory value objects returned from UserStore queries
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActiveDatabaseInfo:
    """Snapshot of the user's inlined active database."""

    name: str
    validation_status: str


@dataclass(frozen=True)
class UserConfig:
    """Machine-auth context returned from API key lookup."""

    user_id: str
    database_url: str | None
    is_active: bool
    onboarding_status: str
    email: str | None
    api_key_id: str | None = None
    scopes: frozenset[str] = frozenset({"mcp_read"})
    key_name: str | None = None
    account_status: str = ACCOUNT_ACTIVE
    plan_code: str = "free"
    billing_status: str = BILLING_FREE


@dataclass(frozen=True)
class UserSessionContext:
    """Session-auth context returned from session token lookup."""

    user_id: str
    email: str
    onboarding_status: str
    is_active: bool
    created_at: datetime
    account_status: str = ACCOUNT_ACTIVE
    plan_code: str = "free"
    billing_status: str = BILLING_FREE


class StateTransitionError(Exception):
    """Raised when a state-gated operation is not allowed."""


class EntitlementExceededError(StateTransitionError):
    """Raised when a user action would exceed a plan limit."""

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
    user_id: str
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
    """User-centric DAO used by the API layer and MCP auth path."""

    def __init__(self, engine: Engine, cipher: CredentialCipher) -> None:
        self._engine = engine
        self._cipher = cipher
        self._entitlements = EntitlementService()

    # ------------------------------------------------------------------
    # User lifecycle
    # ------------------------------------------------------------------

    def create_user(self, email: str) -> str:
        user_id = str(uuid.uuid4())
        now = _utcnow()
        user = User(
            id=user_id,
            email=email.strip().lower(),
            email_verified_at=None,
            onboarding_status="pending_email_verification",
            account_status=ACCOUNT_ACTIVE,
            billing_status=BILLING_FREE,
            plan_code="free",
            daily_query_count=0,
            daily_quota_reset_at=_next_midnight(now),
            db_url_enc=None,
            db_name=None,
            db_validation_status=None,
            db_last_validation_at=None,
            db_last_validation_error=None,
            created_at=now,
            updated_at=now,
            suspended_at=None,
            closed_at=None,
        )
        with Session(self._engine) as session:
            session.add(user)
            session.commit()
        return user_id

    def email_exists(self, email: str) -> bool:
        """Return True if ANY user row (including closed accounts) owns this email."""
        normalized = email.strip().lower()
        with Session(self._engine) as session:
            return session.query(User).filter(User.email == normalized).count() > 0

    def get_user_by_email(self, email: str) -> UserSessionContext | None:
        normalized = email.strip().lower()
        with Session(self._engine) as session:
            user = (
                session.query(User)
                .filter(User.email == normalized, User.account_status != ACCOUNT_CLOSED)
                .first()
            )
            if user is None:
                return None
            return self._session_context_from_user(user)

    def get_user_by_id(self, user_id: str) -> UserConfig | None:
        with Session(self._engine) as session:
            user = session.get(User, user_id)
            if user is None:
                return None
            return self._user_config_from_user(user)

    def get_user_row(self, user_id: str) -> User | None:
        with Session(self._engine) as session:
            user = session.get(User, user_id)
            if user is None:
                return None
            session.expunge(user)
            return user

    def set_email_verified(self, user_id: str) -> bool:
        now = _utcnow()
        with Session(self._engine) as session:
            user = session.get(User, user_id)
            if user is None:
                return False
            user.email_verified_at = now  # type: ignore[assignment]
            user.updated_at = now  # type: ignore[assignment]
            session.commit()
        return True

    def transition_user_state(self, user_id: str, new_onboarding_state: str) -> bool:
        now = _utcnow()
        with Session(self._engine) as session:
            user = session.get(User, user_id)
            if user is None:
                return False
            user.onboarding_status = new_onboarding_state  # type: ignore[assignment]
            user.updated_at = now  # type: ignore[assignment]
            session.commit()
        return True

    def set_account_status(self, user_id: str, new_status: str) -> bool:
        now = _utcnow()
        with Session(self._engine) as session:
            user = session.get(User, user_id)
            if user is None:
                return False
            if str(user.account_status) == ACCOUNT_CLOSED:
                return False
            user.account_status = new_status  # type: ignore[assignment]
            user.updated_at = now  # type: ignore[assignment]
            if new_status == ACCOUNT_SUSPENDED:
                user.suspended_at = now  # type: ignore[assignment]
            if new_status == ACCOUNT_CLOSED:
                user.closed_at = now  # type: ignore[assignment]
            session.commit()
        return True

    def activate_user(self, user_id: str) -> bool:
        """Mark onboarding complete and activate the free plan.

        Sets: onboarding_status=setup_complete, account_status=active,
              billing_status=free, plan_code=free.
        """
        now = _utcnow()
        with Session(self._engine) as session:
            user = session.get(User, user_id)
            if user is None:
                return False
            user.onboarding_status = SETUP_COMPLETE  # type: ignore[assignment]
            user.account_status = ACCOUNT_ACTIVE  # type: ignore[assignment]
            user.billing_status = BILLING_FREE  # type: ignore[assignment]
            user.plan_code = "free"  # type: ignore[assignment]
            user.updated_at = now  # type: ignore[assignment]
            session.commit()
        return True

    def get_user_onboarding_status(self, user_id: str) -> str | None:
        with Session(self._engine) as session:
            user = session.get(User, user_id)
            if user is None:
                return None
            return str(user.onboarding_status)

    def get_user_account_status(self, user_id: str) -> str | None:
        with Session(self._engine) as session:
            user = session.get(User, user_id)
            if user is None:
                return None
            return str(user.account_status)

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def issue_user_session(self, user_id: str, ttl_hours: int = 24) -> str:
        raw_token = "mdbos_" + secrets.token_urlsafe(32)
        now = _utcnow()
        session_hash = _hash_session(raw_token)
        with Session(self._engine) as session:
            user_session = UserSession(
                id=str(uuid.uuid4()),
                user_id=user_id,
                session_hash=session_hash,
                expires_at=now + timedelta(hours=ttl_hours),
                last_used_at=now,
                revoked_at=None,
                created_at=now,
            )
            session.add(user_session)
            session.commit()
        return raw_token

    def get_user_by_session(self, raw_token: str) -> UserSessionContext | None:
        token_hash = _hash_session(raw_token)
        now = _utcnow()
        with Session(self._engine) as session:
            row = (
                session.query(UserSession, User)
                .join(User, UserSession.user_id == User.id)
                .filter(UserSession.session_hash == token_hash)
                .first()
            )
            if row is None:
                return None
            user_session, user = row
            if user_session.revoked_at is not None:
                return None
            if _ensure_utc(user_session.expires_at) < now:
                return None
            if str(user.account_status) in (ACCOUNT_SUSPENDED, ACCOUNT_CLOSED):
                return None
            user_session.last_used_at = now  # type: ignore[assignment]
            session.commit()
            return self._session_context_from_user(user)

    def revoke_user_session(self, raw_token: str) -> bool:
        token_hash = _hash_session(raw_token)
        now = _utcnow()
        with Session(self._engine) as session:
            user_session = (
                session.query(UserSession).filter_by(session_hash=token_hash).first()
            )
            if user_session is None or user_session.revoked_at is not None:
                return False
            user_session.revoked_at = now  # type: ignore[assignment]
            session.commit()
            return True

    # ------------------------------------------------------------------
    # Database registration (inlined on User row)
    # ------------------------------------------------------------------

    def upsert_user_database(
        self, user_id: str, database_url_enc: str, name: str = "primary"
    ) -> bool:
        now = _utcnow()
        with Session(self._engine) as session:
            user = self._lock_user_for_plan_mutation(session, user_id)
            if user is None:
                raise ValueError(f"User {user_id} not found")
            user.db_url_enc = database_url_enc  # type: ignore[assignment]
            user.db_name = name  # type: ignore[assignment]
            user.db_validation_status = "validated"  # type: ignore[assignment]
            user.db_last_validation_at = now  # type: ignore[assignment]
            user.db_last_validation_error = None  # type: ignore[assignment]
            user.updated_at = now  # type: ignore[assignment]
            session.commit()
        return True

    def get_active_database(self, user_id: str) -> ActiveDatabaseInfo | None:
        with Session(self._engine) as session:
            user = session.get(User, user_id)
            if user is None or user.db_url_enc is None:
                return None
            return ActiveDatabaseInfo(
                name=str(user.db_name or "primary"),
                validation_status=str(user.db_validation_status or "validated"),
            )

    # ------------------------------------------------------------------
    # Machine API key lifecycle
    # ------------------------------------------------------------------

    def create_api_key(
        self,
        user_id: str,
        name: str,
        scopes: str | list[str] | tuple[str, ...] | set[str] | frozenset[str],
    ) -> tuple[str, ApiKey]:
        raw_key = "mdbk_" + secrets.token_urlsafe(32)
        now = _utcnow()
        scope_text, _ = _normalize_scopes(scopes)
        api_key = ApiKey(
            id=str(uuid.uuid4()),
            user_id=user_id,
            name=name.strip() or "default",
            prefix=raw_key[:12],
            key_hash=_hash_key(raw_key),
            scope=scope_text,
            last_used_at=None,
            revoked_at=None,
            created_at=now,
        )
        with Session(self._engine) as session:
            user = self._lock_user_for_plan_mutation(session, user_id)
            if user is None:
                raise ValueError(f"User {user_id} not found")
            if str(user.account_status) != ACCOUNT_ACTIVE:
                raise StateTransitionError("User is not eligible to issue API keys.")
            if str(user.onboarding_status) != SETUP_COMPLETE:
                raise StateTransitionError("User is not eligible to issue API keys.")
            if user.db_url_enc is None:
                raise StateTransitionError("User is not eligible to issue API keys.")

            active_count = (
                session.query(ApiKey)
                .filter(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
                .count()
            )
            entitlement = self._entitlements.check_api_key_quota(
                str(user.plan_code), active_count
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

    def list_api_keys(self, user_id: str) -> list[ApiKey]:
        with Session(self._engine) as session:
            rows = (
                session.query(ApiKey)
                .filter(ApiKey.user_id == user_id)
                .order_by(ApiKey.created_at.desc())
                .all()
            )
            for row in rows:
                session.expunge(row)
            return rows

    def revoke_api_key(self, user_id: str, api_key_id: str) -> bool:
        now = _utcnow()
        with Session(self._engine) as session:
            api_key = session.get(ApiKey, api_key_id)
            if api_key is None or str(api_key.user_id) != user_id:
                return False
            if api_key.revoked_at is not None:
                return False
            api_key.revoked_at = now  # type: ignore[assignment]
            session.commit()
            return True

    def rotate_api_key(self, user_id: str, api_key_id: str) -> str:
        with Session(self._engine) as session:
            current = session.get(ApiKey, api_key_id)
            if current is None or str(current.user_id) != user_id:
                raise ValueError(f"API key {api_key_id} not found")
            if current.revoked_at is not None:
                raise StateTransitionError("Cannot rotate a revoked API key.")
            raw_key = "mdbk_" + secrets.token_urlsafe(32)
            now = _utcnow()
            replacement = ApiKey(
                id=str(uuid.uuid4()),
                user_id=user_id,
                name=str(current.name),
                prefix=raw_key[:12],
                key_hash=_hash_key(raw_key),
                scope=str(current.scope),
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
                session.query(ApiKey, User)
                .join(User, ApiKey.user_id == User.id)
                .filter(ApiKey.key_hash == key_hash)
                .first()
            )
            if row is None:
                return None
            api_key, user = row
            if api_key.revoked_at is not None:
                return None
            if str(user.account_status) != ACCOUNT_ACTIVE:
                return None
            if str(user.onboarding_status) != SETUP_COMPLETE:
                return None
            api_key.last_used_at = now  # type: ignore[assignment]
            session.commit()
            return self._api_config_from_rows(api_key, user)

    def get_api_key_metadata(self, api_key_id: str) -> ApiKey | None:
        with Session(self._engine) as session:
            api_key = session.get(ApiKey, api_key_id)
            if api_key is None:
                return None
            session.expunge(api_key)
            return api_key

    def get_active_api_key_for_user_by_raw_key(
        self, user_id: str, raw_key: str
    ) -> ApiKey | None:
        key_hash = _hash_key(raw_key)
        with Session(self._engine) as session:
            api_key = (
                session.query(ApiKey)
                .filter(
                    ApiKey.user_id == user_id,
                    ApiKey.key_hash == key_hash,
                    ApiKey.revoked_at.is_(None),
                )
                .first()
            )
            if api_key is None:
                return None
            session.expunge(api_key)
            return api_key

    def count_active_api_keys(self, user_id: str) -> int:
        with Session(self._engine) as session:
            return (
                session.query(ApiKey)
                .filter(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
                .count()
            )

    def user_can_issue_api_keys(self, user_id: str) -> bool:
        user = self.get_user_row(user_id)
        if user is None:
            return False
        if str(user.account_status) != ACCOUNT_ACTIVE:
            return False
        if str(user.onboarding_status) != SETUP_COMPLETE:
            return False
        return user.db_url_enc is not None

    # ------------------------------------------------------------------
    # Quota
    # ------------------------------------------------------------------

    def consume_daily_query_quota(self, user_id: str) -> DailyQuotaSnapshot:
        now = _utcnow()
        next_reset = _next_midnight(now)

        with Session(self._engine) as session:
            row = session.execute(
                text(
                    """
                    UPDATE users
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
                    WHERE id = :user_id
                    RETURNING plan_code, daily_query_count, daily_quota_reset_at
                    """
                ),
                {"now": now, "next_reset": next_reset, "user_id": user_id},
            ).fetchone()
            session.commit()

        if row is None:
            raise ValueError(f"User {user_id} not found")
        reset_at = row[2]
        if isinstance(reset_at, str):
            reset_at = datetime.fromisoformat(reset_at)
        return DailyQuotaSnapshot(
            user_id=user_id,
            plan_code=str(row[0]),
            daily_count=int(row[1]),
            daily_quota_reset_at=_ensure_utc(reset_at),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _lock_user_for_plan_mutation(self, session: Session, user_id: str) -> User | None:
        if session.bind is None:
            raise RuntimeError("Session is not bound to an engine")
        if session.bind.dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
            return session.get(User, user_id)
        return session.query(User).filter(User.id == user_id).with_for_update().first()

    def _session_context_from_user(self, user: User) -> UserSessionContext:
        onboarding_status = str(user.onboarding_status)
        account_status = str(user.account_status)
        is_active = account_status == ACCOUNT_ACTIVE and onboarding_status == SETUP_COMPLETE
        return UserSessionContext(
            user_id=str(user.id),
            email=str(user.email),
            onboarding_status=onboarding_status,
            account_status=account_status,
            is_active=is_active,
            created_at=_ensure_utc(user.created_at),
            plan_code=str(user.plan_code),
            billing_status=str(user.billing_status),
        )

    def _user_config_from_user(self, user: User) -> UserConfig:
        database_url = None
        if user.db_url_enc is not None:
            database_url = self._cipher.decrypt(str(user.db_url_enc))
        onboarding_status = str(user.onboarding_status)
        account_status = str(user.account_status)
        is_active = account_status == ACCOUNT_ACTIVE and onboarding_status == SETUP_COMPLETE
        return UserConfig(
            user_id=str(user.id),
            database_url=database_url,
            is_active=is_active,
            onboarding_status=onboarding_status,
            account_status=account_status,
            plan_code=str(user.plan_code),
            billing_status=str(user.billing_status),
            email=str(user.email),
            api_key_id=None,
            scopes=frozenset({"mcp_read"}),
            key_name=None,
        )

    def _api_config_from_rows(self, api_key: ApiKey, user: User) -> UserConfig:
        database_url = None
        if user.db_url_enc is not None:
            database_url = self._cipher.decrypt(str(user.db_url_enc))
        _scope_text, scopes = _normalize_scopes(str(api_key.scope))
        return UserConfig(
            user_id=str(user.id),
            database_url=database_url,
            is_active=True,  # already verified account_status==active AND status==setup_complete
            onboarding_status=str(user.onboarding_status),
            account_status=str(user.account_status),
            plan_code=str(user.plan_code),
            billing_status=str(user.billing_status),
            email=str(user.email),
            api_key_id=str(api_key.id),
            scopes=scopes,
            key_name=str(api_key.name),
        )
