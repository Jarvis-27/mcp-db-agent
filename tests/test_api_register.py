"""Focused tests for signup and session-based account status."""

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
    import src.auth.url_guard as ug_module

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    cipher = CredentialCipher([Fernet.generate_key().decode()])
    store = UserStore(engine, cipher)
    token_store = TokenStore(engine)

    api_app.state.user_store = store
    api_app.state.token_store = token_store
    api_app.state.email_sender = LogEmailSender()
    api_app.state.cipher = cipher
    api_app.state.auth_key_cache = TTLCache(maxsize=100, ttl=60)
    api_app.state.user_session_cache = TTLCache(maxsize=100, ttl=60)
    api_app.state.factory = None

    from src.api.app import limiter

    limiter._storage.reset()

    with (
        patch.object(ug_module.settings, "environment", "development"),
        patch("src.api.app.settings") as mock_settings,
    ):
        mock_settings.registration_open = True
        mock_settings.allow_sqlite_user_dbs = False
        mock_settings.billing_gate_enabled = False
        mock_settings.mfa_gate_enabled = False
        mock_settings.register_rate_limit = "100/minute"
        mock_settings.app_base_url = "http://localhost:8000"
        mock_settings.frontend_base_url = "http://localhost:3000"
        mock_settings.user_session_ttl_hours = 24
        yield

    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client():
    return TestClient(api_app)


def test_register_duplicate_email_returns_409(client):
    assert client.post("/v1/auth/signup", json={"email": "dup@example.com"}).status_code == 201
    resp = client.post("/v1/auth/signup", json={"email": "dup@example.com"})
    assert resp.status_code == 409


def test_register_duplicate_email_case_insensitive_returns_409(client):
    """Case-variant of an existing email must be rejected, not allowed through."""
    assert client.post("/v1/auth/signup", json={"email": "Case@Test.com"}).status_code == 201
    resp = client.post("/v1/auth/signup", json={"email": "case@test.com"})
    assert resp.status_code == 409


def test_register_closed_account_email_returns_409(client):
    """Re-registering a closed account's email must return 409, not 500."""
    from src.auth.user_store import UserStore
    from src.auth.onboarding import ACCOUNT_CLOSED

    store: UserStore = api_app.state.user_store
    resp = client.post("/v1/auth/signup", json={"email": "closed@example.com"})
    assert resp.status_code == 201
    user_id = resp.json()["user_id"]
    store.set_account_status(user_id, ACCOUNT_CLOSED)

    resp2 = client.post("/v1/auth/signup", json={"email": "closed@example.com"})
    assert resp2.status_code == 409


def test_register_closed_returns_403(client):
    with patch("src.api.app.settings") as mock_settings:
        mock_settings.registration_open = False
        resp = client.post("/v1/auth/signup", json={"email": "x@example.com"})
    assert resp.status_code == 403


def test_register_missing_email_returns_422(client):
    resp = client.post("/v1/auth/signup", json={})
    assert resp.status_code == 422


def test_register_stores_provided_timezone(client):
    from src.auth.user_store import UserStore

    resp = client.post(
        "/v1/auth/signup",
        json={"email": "ist-signup@example.com", "timezone": "Asia/Kolkata"},
    )
    assert resp.status_code == 201
    user_id = resp.json()["user_id"]

    store: UserStore = api_app.state.user_store
    user = store.get_user_row(user_id)
    assert user is not None
    assert str(user.timezone) == "Asia/Kolkata"


def test_register_without_timezone_defaults_to_utc(client):
    from src.auth.user_store import UserStore

    resp = client.post(
        "/v1/auth/signup",
        json={"email": "no-tz@example.com"},
    )
    assert resp.status_code == 201
    user_id = resp.json()["user_id"]

    store: UserStore = api_app.state.user_store
    user = store.get_user_row(user_id)
    assert user is not None
    assert str(user.timezone) == "UTC"


def test_register_invalid_timezone_silently_uses_utc(client):
    from src.auth.user_store import UserStore

    resp = client.post(
        "/v1/auth/signup",
        json={"email": "bogus-tz@example.com", "timezone": "Not/A_Real_Zone"},
    )
    assert resp.status_code == 201
    user_id = resp.json()["user_id"]

    store: UserStore = api_app.state.user_store
    user = store.get_user_row(user_id)
    assert user is not None
    assert str(user.timezone) == "UTC"


def test_account_status_requires_session(client):
    resp = client.get("/v1/account/status")
    assert resp.status_code == 401


def test_request_login_link_unverified_account_does_not_send_email(client):
    client.post("/v1/auth/signup", json={"email": "unverified@example.com"})

    with patch.object(api_app.state.email_sender, "send_login_email") as send_login_email:
        resp = client.post(
            "/v1/auth/request-login-link",
            json={"email": "unverified@example.com"},
        )

    assert resp.status_code == 202
    send_login_email.assert_not_called()


def test_request_login_link_unknown_email_returns_404(client):
    resp = client.post(
        "/v1/auth/request-login-link",
        json={"email": "no-such-user@example.com"},
    )
    assert resp.status_code == 404
    assert "sign up" in resp.json()["detail"].lower()


def test_exchange_login_link_requires_verified_email(client):
    client.post("/v1/auth/signup", json={"email": "preverify@example.com"})

    store: UserStore = api_app.state.user_store
    token_store: TokenStore = api_app.state.token_store
    ctx = store.get_user_by_email("preverify@example.com")
    assert ctx is not None
    raw_token = token_store.issue_user_login_token(ctx.user_id)

    resp = client.get(f"/v1/auth/exchange-login-link?token={raw_token}")

    assert resp.status_code == 409
    assert "verified" in resp.json()["detail"].lower()


def test_request_and_exchange_login_link_work_after_email_verification(client):
    client.post("/v1/auth/signup", json={"email": "verified@example.com"})

    store: UserStore = api_app.state.user_store
    token_store: TokenStore = api_app.state.token_store
    ctx = store.get_user_by_email("verified@example.com")
    assert ctx is not None

    verify_token = token_store.issue_email_verification_token(ctx.user_id)
    verify_resp = client.get(f"/v1/auth/verify-email?token={verify_token}")
    assert verify_resp.status_code == 200

    with patch.object(api_app.state.email_sender, "send_login_email") as send_login_email:
        request_resp = client.post(
            "/v1/auth/request-login-link",
            json={"email": "verified@example.com"},
        )

    assert request_resp.status_code == 202
    send_login_email.assert_called_once()

    login_token = token_store.issue_user_login_token(ctx.user_id)
    exchange_resp = client.get(f"/v1/auth/exchange-login-link?token={login_token}")

    assert exchange_resp.status_code == 200
    data = exchange_resp.json()
    assert data["status"] == "pending_db_connection"
    assert data["session_token"].startswith("mdbos_")
