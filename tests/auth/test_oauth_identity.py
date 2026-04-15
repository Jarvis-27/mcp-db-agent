"""Unit tests for OAuthIdentityResolver."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from src.auth.crypto import CredentialCipher
from src.auth.oauth_identity import OAuthIdentityError, OAuthIdentityResolver
from src.auth.oauth_verifier import OAuthClaims
from src.auth.user_store import Base, UserConfig, UserStore

_ISSUER = "https://auth.example.com"
_SUBJECT = "oauth2|abc123"
_VALID_DB_URL = "postgresql://user:pass@8.8.8.8/appdb"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store() -> UserStore:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    cipher = CredentialCipher([Fernet.generate_key().decode()])
    return UserStore(engine, cipher)


def _activate_user(store: UserStore, *, email: str = "test@example.com") -> str:
    user_id = store.create_user(email=email)
    store.set_email_verified(user_id)
    store.transition_user_state(user_id, "pending_db_connection")
    store.upsert_user_database(user_id, store._cipher.encrypt(_VALID_DB_URL))
    store.activate_user(user_id)
    return user_id


def _make_claims(
    issuer: str = _ISSUER,
    subject: str = _SUBJECT,
    scopes: frozenset[str] = frozenset({"mcp:access"}),
) -> OAuthClaims:
    return OAuthClaims(
        issuer=issuer,
        subject=subject,
        scopes=scopes,
        expires_at=int(time.time()) + 3600,
        email="oauth@example.com",
    )


# ---------------------------------------------------------------------------
# Happy-path
# ---------------------------------------------------------------------------


def test_resolve_returns_user_config_for_linked_active_user():
    store = _make_store()
    user_id = _activate_user(store)
    store.link_user_oauth_identity(
        user_id, issuer=_ISSUER, subject=_SUBJECT, oauth_email="oauth@example.com"
    )

    resolver = OAuthIdentityResolver(store)
    user_config = resolver.resolve(_make_claims())

    assert user_config.user_id == user_id
    assert user_config.database_url == _VALID_DB_URL
    assert user_config.is_active is True


# ---------------------------------------------------------------------------
# Failure cases
# ---------------------------------------------------------------------------


def test_resolve_raises_no_linked_account():
    store = _make_store()
    resolver = OAuthIdentityResolver(store)

    with pytest.raises(OAuthIdentityError) as exc_info:
        resolver.resolve(_make_claims())

    assert exc_info.value.code == "no_linked_account"


def test_resolve_raises_account_suspended():
    store = _make_store()
    user_id = _activate_user(store)
    store.link_user_oauth_identity(user_id, issuer=_ISSUER, subject=_SUBJECT)
    store.set_account_status(user_id, "suspended")

    resolver = OAuthIdentityResolver(store)
    with pytest.raises(OAuthIdentityError) as exc_info:
        resolver.resolve(_make_claims())
    assert exc_info.value.code == "account_suspended"


def test_resolve_raises_account_closed():
    store = _make_store()
    user_id = _activate_user(store)
    store.link_user_oauth_identity(user_id, issuer=_ISSUER, subject=_SUBJECT)
    store.set_account_status(user_id, "closed")

    resolver = OAuthIdentityResolver(store)
    with pytest.raises(OAuthIdentityError) as exc_info:
        resolver.resolve(_make_claims())
    assert exc_info.value.code == "account_closed"


def test_resolve_raises_setup_incomplete():
    store = _make_store()
    # Create a user but don't complete setup (no DB submitted)
    user_id = store.create_user("incomplete@example.com")
    store.set_email_verified(user_id)
    store.transition_user_state(user_id, "pending_db_connection")
    store.link_user_oauth_identity(user_id, issuer=_ISSUER, subject=_SUBJECT)

    resolver = OAuthIdentityResolver(store)
    with pytest.raises(OAuthIdentityError) as exc_info:
        resolver.resolve(_make_claims())
    assert exc_info.value.code == "setup_incomplete"


def test_resolve_raises_no_database():
    """Setup complete but DB removed from the user row."""
    store = _make_store()
    user_id = _activate_user(store)
    store.link_user_oauth_identity(user_id, issuer=_ISSUER, subject=_SUBJECT)

    # Manually clear the database from the user row
    from sqlalchemy.orm import Session as _Session
    from src.auth.user_store import User as _User
    with _Session(store._engine) as session:
        u = session.get(_User, user_id)
        u.db_url_enc = None  # type: ignore[assignment]
        session.commit()

    resolver = OAuthIdentityResolver(store)
    with pytest.raises(OAuthIdentityError) as exc_info:
        resolver.resolve(_make_claims())
    assert exc_info.value.code == "no_database"


# ---------------------------------------------------------------------------
# last-login update
# ---------------------------------------------------------------------------


def test_resolve_updates_last_login():
    store = _make_store()
    user_id = _activate_user(store)
    store.link_user_oauth_identity(user_id, issuer=_ISSUER, subject=_SUBJECT)

    status_before = store.get_oauth_link_status(user_id)
    # After the initial link, oauth_last_login_at is set by link_user_oauth_identity
    assert status_before is not None
    assert status_before.linked is True

    resolver = OAuthIdentityResolver(store)
    resolver.resolve(_make_claims())

    status_after = store.get_oauth_link_status(user_id)
    assert status_after is not None
    assert status_after.oauth_last_login_at is not None
