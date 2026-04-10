"""Integration tests for the full onboarding flow.

Tests the complete state machine from registration through admin approval,
using TestClient + in-memory SQLite + mocked network calls.
"""

from unittest.mock import patch, MagicMock

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def app_state(tmp_path):
    """Wire up api_app.state with in-memory DB and mocked services."""
    import src.auth.url_guard as ug_module

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    # Also create verification_tokens table
    from src.auth.token_store import VerificationToken
    VerificationToken.__table__.create(bind=engine, checkfirst=True)

    key = Fernet.generate_key().decode()
    cipher = CredentialCipher([key])
    store = UserStore(engine, cipher)
    token_store = TokenStore(engine, email_token_ttl_minutes=60, setup_token_ttl_hours=24)
    email_sender = LogEmailSender()

    api_app.state.user_store = store
    api_app.state.token_store = token_store
    api_app.state.email_sender = email_sender
    api_app.state.cipher = cipher
    api_app.state.auth_key_cache = TTLCache(maxsize=100, ttl=60)
    api_app.state.factory = None

    from src.api.app import limiter
    limiter._storage.reset()

    with patch.object(ug_module.settings, "environment", "development"), \
         patch("src.api.app.settings") as mock_settings:
        mock_settings.registration_open = True
        mock_settings.allow_sqlite_user_dbs = False
        mock_settings.billing_gate_enabled = False
        mock_settings.mfa_gate_enabled = False
        mock_settings.admin_api_key = "test-admin-key-123"
        mock_settings.register_rate_limit = "100/minute"
        mock_settings.app_base_url = "http://localhost:8000"
        yield

    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client():
    return TestClient(api_app, raise_server_exceptions=True)


_VALID_EMAIL = "user@example.com"
_VALID_PG_URL = "postgresql://user:pass@8.8.8.8/mydb"
_ADMIN_KEY = "test-admin-key-123"


def _mock_resolved():
    import socket
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 5432))]


def _register(client, email=_VALID_EMAIL):
    return client.post("/v1/users/register", json={"email": email})


def _get_verification_token(user_id: str) -> str:
    """Extract the most recent email verification token from the TokenStore."""
    token_store: TokenStore = api_app.state.token_store
    from sqlalchemy.orm import Session
    from src.auth.token_store import VerificationToken
    with Session(token_store._engine) as session:
        t = (
            session.query(VerificationToken)
            .filter_by(user_id=user_id, purpose="email_verification")
            .order_by(VerificationToken.expires_at.desc())
            .first()
        )
        assert t is not None, "No verification token found for user"
        # Reconstruct raw token — we can't, so we use a helper hack:
        # Store the raw token on the token store side via mock.
        raise RuntimeError(
            "Cannot extract raw token directly — use _issue_and_capture_token instead."
        )


def _issue_and_capture_token(user_id: str) -> str:
    """Issue a new email verification token and return the raw value."""
    token_store: TokenStore = api_app.state.token_store
    return token_store.issue_email_verification_token(user_id)


def _issue_and_capture_setup_token(user_id: str) -> str:
    token_store: TokenStore = api_app.state.token_store
    return token_store.issue_setup_token(user_id)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_returns_201_pending(client):
    resp = _register(client)
    assert resp.status_code == 201
    data = resp.json()
    assert "user_id" in data
    assert data["status"] == "pending_email_verification"
    assert "api_key" not in data
    assert "message" in data


def test_register_stores_user_as_inactive(client):
    resp = _register(client)
    assert resp.status_code == 201
    user_id = resp.json()["user_id"]
    store: UserStore = api_app.state.user_store
    assert store.get_onboarding_status(user_id) == "pending_email_verification"
    assert store.get_user_by_api_key("mdbk_anything") is None


def test_register_duplicate_email_returns_409(client):
    _register(client, email="dup@example.com")
    resp = _register(client, email="dup@example.com")
    assert resp.status_code == 409


def test_register_database_url_field_rejected(client):
    """Extra field database_url should be rejected (extra='forbid')."""
    resp = client.post(
        "/v1/users/register",
        json={"email": _VALID_EMAIL, "database_url": _VALID_PG_URL},
    )
    assert resp.status_code == 422


def test_register_missing_email_returns_422(client):
    resp = client.post("/v1/users/register", json={})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------


def test_verify_email_advances_state(client):
    resp = _register(client)
    user_id = resp.json()["user_id"]
    raw_token = _issue_and_capture_token(user_id)

    vresp = client.get(f"/v1/onboarding/verify-email?token={raw_token}")
    assert vresp.status_code == 200
    data = vresp.json()
    assert data["user_id"] == user_id
    # With both gates off, should advance to pending_db_connection
    assert data["status"] == "pending_db_connection"
    assert "setup_token" in data
    assert data["setup_token"].startswith("mdbks_")


def test_verify_email_invalid_token_returns_400(client):
    vresp = client.get("/v1/onboarding/verify-email?token=mdbkv_invalid")
    assert vresp.status_code == 400


def test_verify_email_already_used_returns_400(client):
    resp = _register(client)
    user_id = resp.json()["user_id"]
    raw_token = _issue_and_capture_token(user_id)

    client.get(f"/v1/onboarding/verify-email?token={raw_token}")  # first use
    second = client.get(f"/v1/onboarding/verify-email?token={raw_token}")  # second use
    assert second.status_code == 400


def test_verify_email_wrong_state_returns_409(client):
    """If user is already past email verification, re-verification should fail."""
    resp = _register(client)
    user_id = resp.json()["user_id"]
    raw_token = _issue_and_capture_token(user_id)

    # First verification
    client.get(f"/v1/onboarding/verify-email?token={raw_token}")

    # Issue a new token but the user is now in pending_db_connection
    raw_token2 = _issue_and_capture_token(user_id)
    vresp = client.get(f"/v1/onboarding/verify-email?token={raw_token2}")
    assert vresp.status_code == 409


# ---------------------------------------------------------------------------
# Database submission
# ---------------------------------------------------------------------------


def test_submit_database_advances_to_pending_review(client):
    resp = _register(client)
    user_id = resp.json()["user_id"]

    # Advance to pending_db_connection
    raw_token = _issue_and_capture_token(user_id)
    vresp = client.get(f"/v1/onboarding/verify-email?token={raw_token}")
    setup_token = vresp.json()["setup_token"]

    with patch("socket.getaddrinfo", return_value=_mock_resolved()), \
         patch("src.api.app._dry_run_connect"):
        dbr = client.post(
            "/v1/onboarding/database",
            json={"setup_token": setup_token, "database_url": _VALID_PG_URL},
        )

    assert dbr.status_code == 200
    data = dbr.json()
    assert data["user_id"] == user_id
    assert data["status"] == "pending_review"


def test_submit_database_invalid_setup_token_returns_400(client):
    with patch("socket.getaddrinfo", return_value=_mock_resolved()), \
         patch("src.api.app._dry_run_connect"):
        resp = client.post(
            "/v1/onboarding/database",
            json={"setup_token": "mdbks_invalid", "database_url": _VALID_PG_URL},
        )
    assert resp.status_code == 400


def test_submit_database_in_wrong_state_returns_409(client):
    """Cannot submit DB when still in pending_email_verification."""
    resp = _register(client)
    user_id = resp.json()["user_id"]

    # Manually issue a setup token without going through email verification
    setup_token = _issue_and_capture_setup_token(user_id)

    with patch("socket.getaddrinfo", return_value=_mock_resolved()), \
         patch("src.api.app._dry_run_connect"):
        dbr = client.post(
            "/v1/onboarding/database",
            json={"setup_token": setup_token, "database_url": _VALID_PG_URL},
        )
    assert dbr.status_code == 409


def test_submit_database_validates_url(client):
    resp = _register(client)
    user_id = resp.json()["user_id"]
    raw_token = _issue_and_capture_token(user_id)
    vresp = client.get(f"/v1/onboarding/verify-email?token={raw_token}")
    setup_token = vresp.json()["setup_token"]

    with patch("socket.getaddrinfo", return_value=_mock_resolved()), \
         patch("src.api.app._dry_run_connect"):
        dbr = client.post(
            "/v1/onboarding/database",
            json={"setup_token": setup_token, "database_url": "not-a-valid-url"},
        )
    assert dbr.status_code == 400


def test_submit_database_sanitizes_dangerous_params(client):
    """passfile and similar params must be stripped before persistence."""
    resp = _register(client)
    user_id = resp.json()["user_id"]
    raw_token = _issue_and_capture_token(user_id)
    vresp = client.get(f"/v1/onboarding/verify-email?token={raw_token}")
    setup_token = vresp.json()["setup_token"]

    dirty_url = "postgresql://user:pass@8.8.8.8/mydb?passfile=/etc/passwd"
    with patch("socket.getaddrinfo", return_value=_mock_resolved()), \
         patch("src.api.app._dry_run_connect"):
        client.post(
            "/v1/onboarding/database",
            json={"setup_token": setup_token, "database_url": dirty_url},
        )

    # Advance user to active so we can retrieve their config
    store: UserStore = api_app.state.user_store
    store.transition_state(user_id, "pending_review")
    api_key = store.issue_first_api_key(user_id)
    config = store.get_user_by_api_key(api_key)
    assert config is not None
    assert "passfile" not in (config.database_url or "")


# ---------------------------------------------------------------------------
# Admin: approve
# ---------------------------------------------------------------------------


def test_admin_approve_pending_review_user(client):
    resp = _register(client)
    user_id = resp.json()["user_id"]
    raw_token = _issue_and_capture_token(user_id)
    client.get(f"/v1/onboarding/verify-email?token={raw_token}")

    with patch("socket.getaddrinfo", return_value=_mock_resolved()), \
         patch("src.api.app._dry_run_connect"):
        client.post(
            "/v1/onboarding/database",
            json={"setup_token": _issue_and_capture_setup_token(user_id), "database_url": _VALID_PG_URL},
        )

    # At this point setup_token was revoked; user is pending_review
    # Re-issue setup_token to check state
    store: UserStore = api_app.state.user_store
    assert store.get_onboarding_status(user_id) == "pending_review"

    approve = client.post(
        f"/v1/admin/users/{user_id}/approve",
        headers={"X-Admin-Key": _ADMIN_KEY},
    )
    assert approve.status_code == 200
    data = approve.json()
    assert data["status"] == "active"
    assert "api_key" in data
    assert data["api_key"].startswith("mdbk_")
    assert "Store" in data["warning"]


def test_admin_approve_wrong_key_returns_403(client):
    resp = client.post(
        "/v1/admin/users/some-id/approve",
        headers={"X-Admin-Key": "wrong-key"},
    )
    assert resp.status_code == 403


def test_admin_approve_missing_key_returns_403(client):
    resp = client.post("/v1/admin/users/some-id/approve")
    assert resp.status_code == 403


def test_admin_approve_nonexistent_user_returns_404(client):
    resp = client.post(
        "/v1/admin/users/does-not-exist/approve",
        headers={"X-Admin-Key": _ADMIN_KEY},
    )
    assert resp.status_code == 404


def test_admin_approve_wrong_state_returns_409(client):
    """Cannot approve a user still in pending_email_verification."""
    resp = _register(client)
    user_id = resp.json()["user_id"]
    approve = client.post(
        f"/v1/admin/users/{user_id}/approve",
        headers={"X-Admin-Key": _ADMIN_KEY},
    )
    assert approve.status_code == 409


# ---------------------------------------------------------------------------
# Full happy-path end-to-end
# ---------------------------------------------------------------------------


def test_full_happy_path_both_gates_off(client):
    """End-to-end: register → verify email → submit DB → admin approve → use API key."""
    # 1. Register
    reg = _register(client)
    assert reg.status_code == 201
    user_id = reg.json()["user_id"]

    # 2. Verify email
    raw_token = _issue_and_capture_token(user_id)
    verify = client.get(f"/v1/onboarding/verify-email?token={raw_token}")
    assert verify.status_code == 200
    setup_token = verify.json()["setup_token"]
    assert verify.json()["status"] == "pending_db_connection"

    # 3. Submit DB
    with patch("socket.getaddrinfo", return_value=_mock_resolved()), \
         patch("src.api.app._dry_run_connect"):
        db_resp = client.post(
            "/v1/onboarding/database",
            json={"setup_token": setup_token, "database_url": _VALID_PG_URL},
        )
    assert db_resp.status_code == 200
    assert db_resp.json()["status"] == "pending_review"

    # 4. Admin approves
    approve = client.post(
        f"/v1/admin/users/{user_id}/approve",
        headers={"X-Admin-Key": _ADMIN_KEY},
    )
    assert approve.status_code == 200
    api_key = approve.json()["api_key"]
    assert api_key.startswith("mdbk_")

    # 5. Use API key
    me = client.get("/v1/users/me", headers={"X-API-Key": api_key})
    assert me.status_code == 200
    assert me.json()["is_active"] is True


# ---------------------------------------------------------------------------
# Admin: suspend + close
# ---------------------------------------------------------------------------


def _make_active_user(client) -> tuple[str, str]:
    """Register and approve a user. Returns (user_id, api_key)."""
    import uuid as _uuid
    reg = _register(client, email=f"user_{_uuid.uuid4().hex[:8]}@example.com")
    user_id = reg.json()["user_id"]
    # Fast-path to pending_review using the wired cipher
    store: UserStore = api_app.state.user_store
    cipher = api_app.state.cipher
    store.transition_state(user_id, "pending_db_connection")
    store.set_database_url(user_id, cipher.encrypt("postgresql://user:pass@8.8.8.8/mydb"))
    store.transition_state(user_id, "pending_review")
    api_key = store.issue_first_api_key(user_id)
    return user_id, api_key


def test_admin_suspend_active_user(client):
    user_id, _api_key = _make_active_user(client)
    resp = client.post(
        f"/v1/admin/users/{user_id}/suspend",
        headers={"X-Admin-Key": _ADMIN_KEY},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "suspended"


def test_suspended_user_api_key_rejected(client):
    user_id, api_key = _make_active_user(client)
    client.post(
        f"/v1/admin/users/{user_id}/suspend",
        headers={"X-Admin-Key": _ADMIN_KEY},
    )
    # API key should now be rejected
    me = client.get("/v1/users/me", headers={"X-API-Key": api_key})
    assert me.status_code == 401


def test_admin_close_suspended_user(client):
    user_id, _api_key = _make_active_user(client)
    client.post(
        f"/v1/admin/users/{user_id}/suspend",
        headers={"X-Admin-Key": _ADMIN_KEY},
    )
    close = client.post(
        f"/v1/admin/users/{user_id}/close",
        headers={"X-Admin-Key": _ADMIN_KEY},
    )
    assert close.status_code == 200
    assert close.json()["status"] == "closed"


def test_admin_suspend_already_suspended_returns_409(client):
    user_id, _api_key = _make_active_user(client)
    client.post(
        f"/v1/admin/users/{user_id}/suspend",
        headers={"X-Admin-Key": _ADMIN_KEY},
    )
    resp = client.post(
        f"/v1/admin/users/{user_id}/suspend",
        headers={"X-Admin-Key": _ADMIN_KEY},
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# List pending
# ---------------------------------------------------------------------------


def test_list_pending_returns_pending_review_users(client):
    # Add a user in pending_review
    reg = _register(client, email="pending@example.com")
    user_id = reg.json()["user_id"]
    store: UserStore = api_app.state.user_store
    store.transition_state(user_id, "pending_db_connection")
    store.transition_state(user_id, "pending_review")

    resp = client.get(
        "/v1/admin/users/pending",
        headers={"X-Admin-Key": _ADMIN_KEY},
    )
    assert resp.status_code == 200
    items = resp.json()
    assert any(item["user_id"] == user_id for item in items)


def test_list_pending_excludes_active_users(client):
    user_id, _api_key = _make_active_user(client)

    resp = client.get(
        "/v1/admin/users/pending",
        headers={"X-Admin-Key": _ADMIN_KEY},
    )
    assert resp.status_code == 200
    items = resp.json()
    assert not any(item["user_id"] == user_id for item in items)


# ---------------------------------------------------------------------------
# Onboarding status endpoint
# ---------------------------------------------------------------------------


def test_onboarding_status_for_pending_user(client):
    resp = _register(client)
    user_id = resp.json()["user_id"]
    sr = client.get(f"/v1/onboarding/status?user_id={user_id}")
    assert sr.status_code == 200
    assert sr.json()["status"] == "pending_email_verification"
    assert "next_step" in sr.json()


def test_onboarding_status_unknown_user_returns_404(client):
    resp = client.get("/v1/onboarding/status?user_id=does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health_live(client):
    resp = client.get("/health/live")
    assert resp.status_code == 200


def test_health_ready(client):
    resp = client.get("/health/ready")
    assert resp.status_code == 200
