"""Verification token store — email-verification and onboarding-session tokens.

Two token types:
- email_verification (prefix mdbkv_): single-use, short TTL (60 min default).
  Sent in the verification email link.
- setup (prefix mdbks_): multi-use within TTL, longer TTL (24 h default).
  Returned after successful email verification; used to authenticate the
  POST /v1/onboarding/database step.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.orm import Session

from src.auth.user_store import Base, Engine


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TokenNotFoundError(Exception):
    """No token matching the provided value exists."""


class TokenExpiredError(Exception):
    """Token was found but has passed its expiry time."""


class TokenAlreadyUsedError(Exception):
    """Token was already consumed (single-use tokens only)."""


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class VerificationToken(Base):
    __tablename__ = "verification_tokens"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    purpose = Column(String(30), nullable=False)   # 'email_verification' | 'setup'
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# TokenStore
# ---------------------------------------------------------------------------


class TokenStore:
    """Data-access layer for verification_tokens.

    Engine is injected; schema is managed by Alembic.
    """

    PURPOSE_EMAIL = "email_verification"
    PURPOSE_SETUP = "setup"

    def __init__(self, engine: Engine, email_token_ttl_minutes: int = 60, setup_token_ttl_hours: int = 24) -> None:
        self._engine = engine
        self._email_ttl = timedelta(minutes=email_token_ttl_minutes)
        self._setup_ttl = timedelta(hours=setup_token_ttl_hours)

    # ------------------------------------------------------------------
    # Issue tokens
    # ------------------------------------------------------------------

    def issue_email_verification_token(self, user_id: str) -> str:
        """Generate a new email verification token for the user.

        Invalidates any previous unused email_verification tokens for this user
        (by marking them as used) so only the latest link is valid.
        Returns the raw token prefixed with 'mdbkv_'.
        """
        raw_token = "mdbkv_" + secrets.token_urlsafe(32)
        token_hash = _hash_token(raw_token)
        now = _utcnow()
        expires_at = now + self._email_ttl

        with Session(self._engine) as session:
            # Invalidate previous unused tokens for this user + purpose
            session.query(VerificationToken).filter(
                VerificationToken.user_id == user_id,
                VerificationToken.purpose == self.PURPOSE_EMAIL,
                VerificationToken.used_at.is_(None),
            ).update({"used_at": now})

            token = VerificationToken(
                id=str(uuid.uuid4()),
                user_id=user_id,
                token_hash=token_hash,
                purpose=self.PURPOSE_EMAIL,
                expires_at=expires_at,
                used_at=None,
            )
            session.add(token)
            session.commit()

        return raw_token

    def issue_setup_token(self, user_id: str) -> str:
        """Generate a new setup session token for post-verification onboarding steps.

        Invalidates any previous unused setup tokens for this user.
        Returns the raw token prefixed with 'mdbks_'.
        """
        raw_token = "mdbks_" + secrets.token_urlsafe(32)
        token_hash = _hash_token(raw_token)
        now = _utcnow()
        expires_at = now + self._setup_ttl

        with Session(self._engine) as session:
            # Invalidate previous unused setup tokens for this user
            session.query(VerificationToken).filter(
                VerificationToken.user_id == user_id,
                VerificationToken.purpose == self.PURPOSE_SETUP,
                VerificationToken.used_at.is_(None),
            ).update({"used_at": now})

            token = VerificationToken(
                id=str(uuid.uuid4()),
                user_id=user_id,
                token_hash=token_hash,
                purpose=self.PURPOSE_SETUP,
                expires_at=expires_at,
                used_at=None,
            )
            session.add(token)
            session.commit()

        return raw_token

    # ------------------------------------------------------------------
    # Verify tokens
    # ------------------------------------------------------------------

    def verify_email_token(self, raw_token: str) -> str:
        """Validate and consume an email verification token.

        Returns the user_id on success.
        Raises:
          TokenNotFoundError — token hash not in DB
          TokenExpiredError — token exists but is past expires_at
          TokenAlreadyUsedError — token was already consumed
        """
        token_hash = _hash_token(raw_token)
        now = _utcnow()

        with Session(self._engine) as session:
            token = session.query(VerificationToken).filter_by(token_hash=token_hash).first()

            if token is None:
                raise TokenNotFoundError("Email verification token not found.")

            if token.purpose != self.PURPOSE_EMAIL:
                raise TokenNotFoundError("Token is not an email verification token.")

            if token.used_at is not None:
                raise TokenAlreadyUsedError("Email verification token has already been used.")

            if _ensure_utc(token.expires_at) < now:
                raise TokenExpiredError("Email verification token has expired.")

            # Consume the token
            token.used_at = now  # type: ignore[assignment]
            user_id = str(token.user_id)
            session.commit()

        return user_id

    def verify_setup_token(self, raw_token: str) -> str:
        """Validate a setup session token (multi-use — does NOT mark as used).

        Returns the user_id on success.
        Raises:
          TokenNotFoundError — token hash not in DB
          TokenExpiredError — token exists but is past expires_at
        """
        token_hash = _hash_token(raw_token)
        now = _utcnow()

        with Session(self._engine) as session:
            token = session.query(VerificationToken).filter_by(token_hash=token_hash).first()

            if token is None:
                raise TokenNotFoundError("Setup token not found.")

            if token.purpose != self.PURPOSE_SETUP:
                raise TokenNotFoundError("Token is not a setup token.")

            if token.used_at is not None:
                raise TokenExpiredError("Setup token has been revoked.")

            if _ensure_utc(token.expires_at) < now:
                raise TokenExpiredError("Setup token has expired.")

            return str(token.user_id)

    # ------------------------------------------------------------------
    # Revoke
    # ------------------------------------------------------------------

    def revoke_setup_token(self, user_id: str) -> None:
        """Mark all setup tokens for the user as used (revoked).

        Called after the database connection is successfully submitted so the
        setup token cannot be reused for a different database URL.
        """
        now = _utcnow()
        with Session(self._engine) as session:
            session.query(VerificationToken).filter(
                VerificationToken.user_id == user_id,
                VerificationToken.purpose == self.PURPOSE_SETUP,
                VerificationToken.used_at.is_(None),
            ).update({"used_at": now})
            session.commit()
