"""Tests for src/auth/token_store.py."""

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
from src.auth.user_store import Base, UserStore
from src.auth.crypto import CredentialCipher
from cryptography.fernet import Fernet


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
    return TokenStore(engine, email_token_ttl_minutes=60, login_token_ttl_minutes=30)


@pytest.fixture
def membership_id(engine):
    cipher = CredentialCipher([Fernet.generate_key().decode()])
    user_store = UserStore(engine, cipher)
    _tenant_id, membership_id = user_store.create_tenant_with_owner("test@example.com")
    return membership_id


def test_issue_email_token_prefix(store, membership_id):
    token = store.issue_email_verification_token(membership_id)
    assert token.startswith("mdbkv_")


def test_verify_email_token_returns_membership_id(store, membership_id):
    raw = store.issue_email_verification_token(membership_id)
    assert store.verify_email_token(raw) == membership_id


def test_verify_email_token_is_single_use(store, membership_id):
    raw = store.issue_email_verification_token(membership_id)
    store.verify_email_token(raw)
    with pytest.raises(TokenAlreadyUsedError):
        store.verify_email_token(raw)


def test_verify_email_token_not_found(store, membership_id):
    with pytest.raises(TokenNotFoundError):
        store.verify_email_token("mdbkv_doesnotexist")


def test_verify_email_token_expired(store, membership_id, engine):
    raw = store.issue_email_verification_token(membership_id)
    token_hash = __import__("hashlib").sha256(raw.encode()).hexdigest()
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        token = session.query(VerificationToken).filter_by(token_hash=token_hash).first()
        token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    with pytest.raises(TokenExpiredError):
        store.verify_email_token(raw)


def test_issue_login_token_prefix(store, membership_id):
    token = store.issue_owner_login_token(membership_id)
    assert token.startswith("mdbl_")


def test_verify_login_token_returns_membership_id(store, membership_id):
    raw = store.issue_owner_login_token(membership_id)
    assert store.verify_owner_login_token(raw) == membership_id


def test_verify_login_token_is_single_use(store, membership_id):
    raw = store.issue_owner_login_token(membership_id)
    store.verify_owner_login_token(raw)
    with pytest.raises(TokenAlreadyUsedError):
        store.verify_owner_login_token(raw)


def test_verify_login_token_wrong_purpose(store, membership_id):
    raw = store.issue_email_verification_token(membership_id)
    with pytest.raises(TokenNotFoundError):
        store.verify_owner_login_token(raw)
