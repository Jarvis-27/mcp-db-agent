"""User model and data-access layer for multi-tenant auth."""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Engine,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Session

from src.auth.crypto import CredentialCipher
from src.auth.url_guard import validate_database_url


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    api_key_hash = Column(String(64), unique=True, nullable=False, index=True)
    database_url_enc = Column(Text, nullable=False)
    llm_provider = Column(String(20), nullable=False)
    anthropic_api_key_enc = Column(Text, nullable=True)
    groq_api_key_enc = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    daily_query_count = Column(Integer, nullable=False, default=0)
    daily_quota_reset_at = Column(DateTime(timezone=True), nullable=False)


class QueryHistory(Base):
    """Query history table — managed via Alembic, defined here for autogenerate."""

    __tablename__ = "query_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    user_id = Column(String(36), nullable=False)
    question = Column(Text, nullable=False)
    sql = Column(Text, nullable=False)
    success = Column(Boolean, nullable=False)
    row_count = Column(Integer, nullable=True)
    attempts = Column(Integer, nullable=False)
    duration_ms = Column(Integer, nullable=False)
    error = Column(Text, nullable=True)

    __table_args__ = (Index("ix_query_history_user_id_desc", "user_id", "id"),)


@dataclass(frozen=True)
class UserConfig:
    """In-memory user data — never persisted, returned from UserStore."""

    user_id: str
    database_url: str  # decrypted, already passed url_guard
    is_active: bool


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _ensure_utc(dt: datetime) -> datetime:
    """SQLite returns naive datetimes. Treat them as UTC for comparison."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _midnight_tomorrow() -> datetime:
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).replace(
        day=now.day + 1
    ) if now.day < 28 else _next_midnight(now)


def _next_midnight(now: datetime) -> datetime:
    """Return UTC midnight of the next calendar day."""
    from datetime import timedelta

    return (now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))


class UserStore:
    """Data-access object for the users table.

    Schema is managed by Alembic — this class does NOT call create_all.
    The engine is injected so tests can use in-memory SQLite.
    """

    def __init__(self, engine: Engine, cipher: CredentialCipher) -> None:
        self._engine = engine
        self._cipher = cipher

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def create_user(self, database_url: str) -> tuple[str, str]:
        """Create a new user. Returns (user_id, raw_api_key).

        raw_api_key format: 'mdbk_' + secrets.token_urlsafe(32).
        Stores SHA-256(raw_api_key) only — the raw key is never stored.
        """
        # Validate URL before storing
        validate_database_url(database_url)

        raw_key = "mdbk_" + secrets.token_urlsafe(32)
        user_id = str(uuid.uuid4())
        now = _utcnow()

        user = User(
            id=user_id,
            api_key_hash=_hash_key(raw_key),
            database_url_enc=self._cipher.encrypt(database_url),
            llm_provider="server",
            is_active=True,
            created_at=now,
            updated_at=now,
            daily_query_count=0,
            daily_quota_reset_at=_next_midnight(now),
        )

        with Session(self._engine) as session:
            session.add(user)
            session.commit()

        return user_id, raw_key

    def update_user(self, user_id: str, *, database_url: str | None = None) -> bool:
        """Update the database URL for a user. Refreshes updated_at. Returns False if not found."""
        with Session(self._engine) as session:
            user = session.get(User, user_id)
            if user is None:
                return False

            if database_url is not None:
                validate_database_url(database_url)
                user.database_url_enc = self._cipher.encrypt(database_url)

            user.updated_at = _utcnow()
            session.commit()

        return True

    def rotate_api_key(self, user_id: str) -> str:
        """Generate a new raw key, replace api_key_hash, return new raw key.

        Caller is responsible for invalidating auth-key cache and cached pipelines.
        """
        raw_key = "mdbk_" + secrets.token_urlsafe(32)
        with Session(self._engine) as session:
            user = session.get(User, user_id)
            if user is None:
                raise ValueError(f"User {user_id} not found")
            user.api_key_hash = _hash_key(raw_key)
            user.updated_at = _utcnow()
            session.commit()
        return raw_key

    def deactivate_user(self, user_id: str) -> bool:
        """Deactivate a user. Returns False if not found."""
        with Session(self._engine) as session:
            user = session.get(User, user_id)
            if user is None:
                return False
            user.is_active = False
            user.updated_at = _utcnow()
            session.commit()
        return True

    def increment_daily_quota(self, user_id: str) -> int:
        """Atomic counter increment with daily reset. Returns new count.

        Resets the counter if daily_quota_reset_at has passed.
        """
        with Session(self._engine) as session:
            user = session.get(User, user_id)
            if user is None:
                raise ValueError(f"User {user_id} not found")

            now = _utcnow()
            if now >= _ensure_utc(user.daily_quota_reset_at):
                user.daily_query_count = 1
                user.daily_quota_reset_at = _next_midnight(now)
            else:
                user.daily_query_count = (user.daily_query_count or 0) + 1

            count = user.daily_query_count
            session.commit()

        return count

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_user_by_api_key(self, raw_key: str) -> UserConfig | None:
        """Hash → DB lookup → decrypt → return UserConfig.

        Returns None if key not found or user is inactive.
        """
        key_hash = _hash_key(raw_key)
        with Session(self._engine) as session:
            user = session.query(User).filter_by(api_key_hash=key_hash).first()
            if user is None or not user.is_active:
                return None
            return self._to_config(user)

    def get_user_by_id(self, user_id: str) -> UserConfig | None:
        """Look up user by ID. Returns None if not found."""
        with Session(self._engine) as session:
            user = session.get(User, user_id)
            if user is None:
                return None
            return self._to_config(user)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _to_config(self, user: User) -> UserConfig:
        return UserConfig(
            user_id=user.id,
            database_url=self._cipher.decrypt(user.database_url_enc),
            is_active=user.is_active,
        )
