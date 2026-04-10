"""Focused tests for admin key validation and admin endpoint access control."""

from unittest.mock import patch

import pytest
from cachetools import TTLCache
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from src.api.app import api_app
from src.auth.crypto import CredentialCipher
from src.auth.token_store import TokenStore
from src.auth.user_store import Base, UserStore
from src.email_sender import LogEmailSender


@pytest.fixture(autouse=True)
def app_state():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    from src.auth.token_store import VerificationToken
    VerificationToken.__table__.create(bind=engine, checkfirst=True)

    key = Fernet.generate_key().decode()
    cipher = CredentialCipher([key])
    store = UserStore(engine, cipher)
    token_store = TokenStore(engine)

    api_app.state.user_store = store
    api_app.state.token_store = token_store
    api_app.state.email_sender = LogEmailSender()
    api_app.state.cipher = cipher
    api_app.state.auth_key_cache = TTLCache(maxsize=100, ttl=60)
    api_app.state.factory = None

    from src.api.app import limiter
    limiter._storage.reset()

    with patch("src.api.app.settings") as mock_settings:
        mock_settings.admin_api_key = "correct-admin-key"
        mock_settings.registration_open = True
        mock_settings.billing_gate_enabled = False
        mock_settings.mfa_gate_enabled = False
        mock_settings.register_rate_limit = "100/minute"
        mock_settings.app_base_url = "http://localhost:8000"
        mock_settings.allow_sqlite_user_dbs = False
        yield

    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client():
    return TestClient(api_app, raise_server_exceptions=True)


def _make_pending_review_user() -> str:
    """Create a user and advance to pending_review."""
    import uuid
    store: UserStore = api_app.state.user_store
    cipher = api_app.state.cipher
    user_id = store.create_user(email=f"{uuid.uuid4()}@example.com")
    store.transition_state(user_id, "pending_db_connection")
    store.set_database_url(user_id, cipher.encrypt("postgresql://user:pass@8.8.8.8/mydb"))
    store.transition_state(user_id, "pending_review")
    return user_id


# ---------------------------------------------------------------------------
# Admin key validation
# ---------------------------------------------------------------------------


def test_missing_admin_key_returns_403(client):
    resp = client.post("/v1/admin/users/some-id/approve")
    assert resp.status_code == 403


def test_wrong_admin_key_returns_403(client):
    resp = client.post(
        "/v1/admin/users/some-id/approve",
        headers={"X-Admin-Key": "wrong-key"},
    )
    assert resp.status_code == 403


def test_correct_admin_key_passes_auth(client):
    """A 404 means the key was accepted (user just doesn't exist)."""
    resp = client.post(
        "/v1/admin/users/does-not-exist/approve",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    assert resp.status_code == 404


def test_admin_key_required_on_suspend(client):
    resp = client.post("/v1/admin/users/some-id/suspend")
    assert resp.status_code == 403


def test_admin_key_required_on_close(client):
    resp = client.post("/v1/admin/users/some-id/close")
    assert resp.status_code == 403


def test_admin_key_required_on_list_pending(client):
    resp = client.get("/v1/admin/users/pending")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# List pending users
# ---------------------------------------------------------------------------


def test_list_pending_returns_only_pending_review_users(client):
    uid1 = _make_pending_review_user()
    uid2 = _make_pending_review_user()

    # Also create a user not in pending_review
    store: UserStore = api_app.state.user_store
    uid_other = store.create_user(email="other@example.com")
    # uid_other stays in pending_email_verification

    resp = client.get(
        "/v1/admin/users/pending",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    assert resp.status_code == 200
    items = resp.json()
    returned_ids = {i["user_id"] for i in items}
    assert uid1 in returned_ids
    assert uid2 in returned_ids
    assert uid_other not in returned_ids


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------


def test_approve_pending_review_user_returns_active_and_key(client):
    user_id = _make_pending_review_user()
    resp = client.post(
        f"/v1/admin/users/{user_id}/approve",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"
    assert data["api_key"].startswith("mdbk_")


def test_approve_nonexistent_user_returns_404(client):
    resp = client.post(
        "/v1/admin/users/does-not-exist/approve",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    assert resp.status_code == 404


def test_approve_wrong_state_returns_409(client):
    store: UserStore = api_app.state.user_store
    user_id = store.create_user(email="early@example.com")
    resp = client.post(
        f"/v1/admin/users/{user_id}/approve",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Suspend
# ---------------------------------------------------------------------------


def test_suspend_active_user(client):
    user_id = _make_pending_review_user()
    # Approve first
    client.post(
        f"/v1/admin/users/{user_id}/approve",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    resp = client.post(
        f"/v1/admin/users/{user_id}/suspend",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "suspended"


def test_suspend_already_suspended_returns_409(client):
    user_id = _make_pending_review_user()
    client.post(
        f"/v1/admin/users/{user_id}/approve",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    client.post(
        f"/v1/admin/users/{user_id}/suspend",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    resp = client.post(
        f"/v1/admin/users/{user_id}/suspend",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    assert resp.status_code == 409


def test_suspend_pending_review_user_returns_409(client):
    """Cannot suspend a user who hasn't been approved yet."""
    user_id = _make_pending_review_user()
    resp = client.post(
        f"/v1/admin/users/{user_id}/suspend",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Close
# ---------------------------------------------------------------------------


def test_close_suspended_user(client):
    user_id = _make_pending_review_user()
    client.post(
        f"/v1/admin/users/{user_id}/approve",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    client.post(
        f"/v1/admin/users/{user_id}/suspend",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    resp = client.post(
        f"/v1/admin/users/{user_id}/close",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"


def test_close_active_user(client):
    user_id = _make_pending_review_user()
    client.post(
        f"/v1/admin/users/{user_id}/approve",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    resp = client.post(
        f"/v1/admin/users/{user_id}/close",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"


def test_close_closed_user_returns_409(client):
    user_id = _make_pending_review_user()
    client.post(
        f"/v1/admin/users/{user_id}/approve",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    client.post(
        f"/v1/admin/users/{user_id}/close",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    resp = client.post(
        f"/v1/admin/users/{user_id}/close",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    assert resp.status_code == 409
