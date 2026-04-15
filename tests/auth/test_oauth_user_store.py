"""Tests for UserStore OAuth identity linkage methods."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from src.auth.crypto import CredentialCipher
from src.auth.user_store import Base, StateTransitionError, UserStore

_ISSUER = "https://auth.example.com"
_SUBJECT = "oauth2|abc"
_VALID_DB_URL = "postgresql://user:pass@8.8.8.8/db"


def _make_store() -> UserStore:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return UserStore(engine, CredentialCipher([Fernet.generate_key().decode()]))


def _activate_user(store: UserStore, email: str = "user@example.com") -> str:
    uid = store.create_user(email)
    store.set_email_verified(uid)
    store.transition_user_state(uid, "pending_db_connection")
    store.upsert_user_database(uid, store._cipher.encrypt(_VALID_DB_URL))
    store.activate_user(uid)
    return uid


# ---------------------------------------------------------------------------
# get_oauth_link_status
# ---------------------------------------------------------------------------


def test_get_oauth_link_status_returns_none_for_missing_user():
    store = _make_store()
    assert store.get_oauth_link_status("does-not-exist") is None


def test_get_oauth_link_status_unlinked():
    store = _make_store()
    uid = _activate_user(store)
    status = store.get_oauth_link_status(uid)
    assert status is not None
    assert status.linked is False
    assert status.issuer is None
    assert status.subject is None


# ---------------------------------------------------------------------------
# link_user_oauth_identity
# ---------------------------------------------------------------------------


def test_link_stores_issuer_and_subject():
    store = _make_store()
    uid = _activate_user(store)
    ok = store.link_user_oauth_identity(
        uid, issuer=_ISSUER, subject=_SUBJECT, oauth_email="me@example.com"
    )
    assert ok is True

    status = store.get_oauth_link_status(uid)
    assert status is not None
    assert status.linked is True
    assert status.issuer == _ISSUER
    assert status.subject == _SUBJECT
    assert status.oauth_email == "me@example.com"


def test_link_same_identity_to_same_user_is_idempotent():
    store = _make_store()
    uid = _activate_user(store)
    store.link_user_oauth_identity(uid, issuer=_ISSUER, subject=_SUBJECT)
    # Linking again to the same user should succeed
    ok = store.link_user_oauth_identity(uid, issuer=_ISSUER, subject=_SUBJECT)
    assert ok is True


def test_link_raises_on_identity_conflict():
    store = _make_store()
    uid1 = _activate_user(store, "a@example.com")
    uid2 = _activate_user(store, "b@example.com")
    store.link_user_oauth_identity(uid1, issuer=_ISSUER, subject=_SUBJECT)

    with pytest.raises(StateTransitionError, match="different account"):
        store.link_user_oauth_identity(uid2, issuer=_ISSUER, subject=_SUBJECT)


def test_link_returns_false_for_missing_user():
    store = _make_store()
    result = store.link_user_oauth_identity("no-such-user", issuer=_ISSUER, subject=_SUBJECT)
    assert result is False


# ---------------------------------------------------------------------------
# get_user_by_oauth_subject
# ---------------------------------------------------------------------------


def test_get_user_by_oauth_subject_returns_none_when_not_linked():
    store = _make_store()
    assert store.get_user_by_oauth_subject(_ISSUER, _SUBJECT) is None


def test_get_user_by_oauth_subject_returns_user_config():
    store = _make_store()
    uid = _activate_user(store)
    store.link_user_oauth_identity(uid, issuer=_ISSUER, subject=_SUBJECT)

    uc = store.get_user_by_oauth_subject(_ISSUER, _SUBJECT)
    assert uc is not None
    assert uc.user_id == uid
    assert uc.database_url == _VALID_DB_URL


# ---------------------------------------------------------------------------
# unlink_oauth_identity
# ---------------------------------------------------------------------------


def test_unlink_clears_fields():
    store = _make_store()
    uid = _activate_user(store)
    store.link_user_oauth_identity(uid, issuer=_ISSUER, subject=_SUBJECT)

    ok = store.unlink_oauth_identity(uid)
    assert ok is True

    status = store.get_oauth_link_status(uid)
    assert status is not None
    assert status.linked is False

    # The previously linked identity should no longer resolve
    assert store.get_user_by_oauth_subject(_ISSUER, _SUBJECT) is None


def test_unlink_returns_false_for_missing_user():
    store = _make_store()
    assert store.unlink_oauth_identity("no-such") is False


# ---------------------------------------------------------------------------
# update_oauth_last_login
# ---------------------------------------------------------------------------


def test_update_last_login_no_error_on_missing():
    """Calling update_oauth_last_login on an unlinkable subject is a no-op."""
    store = _make_store()
    # Should not raise
    store.update_oauth_last_login("https://x.example.com", "no-such-subject")


def test_update_last_login_sets_timestamp():
    store = _make_store()
    uid = _activate_user(store)
    store.link_user_oauth_identity(uid, issuer=_ISSUER, subject=_SUBJECT)

    store.update_oauth_last_login(_ISSUER, _SUBJECT)
    status = store.get_oauth_link_status(uid)
    assert status is not None
    assert status.oauth_last_login_at is not None
