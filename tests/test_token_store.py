"""Tests for src/auth/token_store.py — token lifecycle."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from src.auth.token_store import (
    TokenAlreadyUsedError,
    TokenExpiredError,
    TokenNotFoundError,
    TokenStore,
    VerificationToken,
)
from src.auth.user_store import Base, User


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def store(engine):
    return TokenStore(engine, email_token_ttl_minutes=60, setup_token_ttl_hours=24)


@pytest.fixture
def user_id(engine):
    """Insert a minimal user row so FK constraints pass."""
    from sqlalchemy.orm import Session
    from datetime import UTC, datetime

    uid = str(uuid.uuid4())
    now = datetime.now(UTC)
    with Session(engine) as session:
        session.add(User(
            id=uid,
            api_key_hash=None,
            database_url_enc=None,
            llm_provider="server",
            is_active=False,
            created_at=now,
            updated_at=now,
            daily_query_count=0,
            daily_quota_reset_at=now,
            email="test@example.com",
            onboarding_status="pending_email_verification",
            email_verified_at=None,
        ))
        session.commit()
    return uid


# ---------------------------------------------------------------------------
# Email verification tokens
# ---------------------------------------------------------------------------


def test_issue_email_token_prefix(store, user_id):
    token = store.issue_email_verification_token(user_id)
    assert token.startswith("mdbkv_")


def test_verify_email_token_returns_user_id(store, user_id):
    raw = store.issue_email_verification_token(user_id)
    result = store.verify_email_token(raw)
    assert result == user_id


def test_verify_email_token_is_single_use(store, user_id):
    raw = store.issue_email_verification_token(user_id)
    store.verify_email_token(raw)  # first use succeeds
    with pytest.raises(TokenAlreadyUsedError):
        store.verify_email_token(raw)  # second use fails


def test_verify_email_token_not_found(store, user_id):
    with pytest.raises(TokenNotFoundError):
        store.verify_email_token("mdbkv_doesnotexist")


def test_verify_email_token_expired(store, user_id, engine):
    raw = store.issue_email_verification_token(user_id)
    # Force expiry by back-dating the token
    from sqlalchemy.orm import Session
    import hashlib
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    with Session(engine) as session:
        t = session.query(VerificationToken).filter_by(token_hash=token_hash).first()
        t.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    with pytest.raises(TokenExpiredError):
        store.verify_email_token(raw)


def test_new_email_token_invalidates_previous(store, user_id):
    """Issuing a second email token revokes the first one."""
    raw_first = store.issue_email_verification_token(user_id)
    _raw_second = store.issue_email_verification_token(user_id)

    with pytest.raises(TokenAlreadyUsedError):
        store.verify_email_token(raw_first)


def test_verify_email_token_wrong_purpose(store, user_id):
    """A setup token cannot be used as an email verification token."""
    raw = store.issue_setup_token(user_id)
    with pytest.raises(TokenNotFoundError):
        store.verify_email_token(raw)


# ---------------------------------------------------------------------------
# Setup tokens
# ---------------------------------------------------------------------------


def test_issue_setup_token_prefix(store, user_id):
    token = store.issue_setup_token(user_id)
    assert token.startswith("mdbks_")


def test_verify_setup_token_returns_user_id(store, user_id):
    raw = store.issue_setup_token(user_id)
    result = store.verify_setup_token(raw)
    assert result == user_id


def test_setup_token_is_multi_use(store, user_id):
    raw = store.issue_setup_token(user_id)
    store.verify_setup_token(raw)  # first call
    store.verify_setup_token(raw)  # second call — should not raise


def test_verify_setup_token_not_found(store, user_id):
    with pytest.raises(TokenNotFoundError):
        store.verify_setup_token("mdbks_doesnotexist")


def test_verify_setup_token_expired(store, user_id, engine):
    raw = store.issue_setup_token(user_id)
    import hashlib
    from sqlalchemy.orm import Session
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    with Session(engine) as session:
        t = session.query(VerificationToken).filter_by(token_hash=token_hash).first()
        t.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    with pytest.raises(TokenExpiredError):
        store.verify_setup_token(raw)


def test_revoke_setup_token(store, user_id):
    raw = store.issue_setup_token(user_id)
    store.revoke_setup_token(user_id)
    with pytest.raises(TokenExpiredError):
        store.verify_setup_token(raw)


def test_new_setup_token_invalidates_previous(store, user_id):
    raw_first = store.issue_setup_token(user_id)
    _raw_second = store.issue_setup_token(user_id)

    with pytest.raises(TokenExpiredError):
        store.verify_setup_token(raw_first)


def test_verify_setup_token_wrong_purpose(store, user_id):
    """An email verification token cannot be used as a setup token."""
    raw = store.issue_email_verification_token(user_id)
    with pytest.raises(TokenNotFoundError):
        store.verify_setup_token(raw)
