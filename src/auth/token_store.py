"""Token store for email-verification and user login links."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.orm import Session

from src.auth.user_store import Base, Engine


class TokenNotFoundError(Exception):
    """No token matching the provided value exists."""


class TokenExpiredError(Exception):
    """Token was found but has passed its expiry time."""


class TokenAlreadyUsedError(Exception):
    """Token was already consumed."""


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
    purpose = Column(String(30), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


class TokenStore:
    PURPOSE_EMAIL = "email_verification"
    PURPOSE_USER_LOGIN = "user_login"

    def __init__(
        self,
        engine: Engine,
        email_token_ttl_minutes: int = 60,
        login_token_ttl_minutes: int = 30,
    ) -> None:
        self._engine = engine
        self._email_ttl = timedelta(minutes=email_token_ttl_minutes)
        self._login_ttl = timedelta(minutes=login_token_ttl_minutes)

    def issue_email_verification_token(self, user_id: str) -> str:
        return self._issue_token(
            user_id=user_id,
            purpose=self.PURPOSE_EMAIL,
            prefix="mdbkv_",
            ttl=self._email_ttl,
        )

    def issue_user_login_token(self, user_id: str) -> str:
        return self._issue_token(
            user_id=user_id,
            purpose=self.PURPOSE_USER_LOGIN,
            prefix="mdbl_",
            ttl=self._login_ttl,
        )

    def verify_email_token(self, raw_token: str) -> str:
        return self._consume_token(raw_token, self.PURPOSE_EMAIL)

    def verify_user_login_token(self, raw_token: str) -> str:
        return self._consume_token(raw_token, self.PURPOSE_USER_LOGIN)

    def _issue_token(
        self,
        *,
        user_id: str,
        purpose: str,
        prefix: str,
        ttl: timedelta,
    ) -> str:
        raw_token = prefix + secrets.token_urlsafe(32)
        token_hash = _hash_token(raw_token)
        now = _utcnow()

        with Session(self._engine) as session:
            # Invalidate any previous unused tokens for the same user + purpose
            session.query(VerificationToken).filter(
                VerificationToken.user_id == user_id,
                VerificationToken.purpose == purpose,
                VerificationToken.used_at.is_(None),
            ).update({"used_at": now})

            token = VerificationToken(
                id=str(uuid.uuid4()),
                user_id=user_id,
                token_hash=token_hash,
                purpose=purpose,
                expires_at=now + ttl,
                used_at=None,
            )
            session.add(token)
            session.commit()

        return raw_token

    def _consume_token(self, raw_token: str, expected_purpose: str) -> str:
        token_hash = _hash_token(raw_token)
        now = _utcnow()

        with Session(self._engine) as session:
            token = session.query(VerificationToken).filter_by(token_hash=token_hash).first()
            if token is None:
                raise TokenNotFoundError("Token not found.")
            if token.purpose != expected_purpose:
                raise TokenNotFoundError("Token purpose mismatch.")
            if token.used_at is not None:
                raise TokenAlreadyUsedError("Token has already been used.")
            if _ensure_utc(token.expires_at) < now:
                raise TokenExpiredError("Token has expired.")
            token.used_at = now  # type: ignore[assignment]
            user_id = str(token.user_id)
            session.commit()
            return user_id
