"""Focused tests for registration and owner-session onboarding status."""

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
    api_app.state.owner_session_cache = TTLCache(maxsize=100, ttl=60)
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
        mock_settings.admin_api_key = "test-admin-key"
        mock_settings.register_rate_limit = "100/minute"
        mock_settings.app_base_url = "http://localhost:8000"
        mock_settings.frontend_base_url = "http://localhost:3000"
        mock_settings.owner_session_ttl_hours = 24
        yield

    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client():
    return TestClient(api_app)


def test_register_duplicate_email_returns_409(client):
    assert client.post("/v1/users/register", json={"email": "dup@example.com"}).status_code == 201
    resp = client.post("/v1/users/register", json={"email": "dup@example.com"})
    assert resp.status_code == 409


def test_register_closed_returns_403(client):
    with patch("src.api.app.settings") as mock_settings:
        mock_settings.registration_open = False
        resp = client.post("/v1/users/register", json={"email": "x@example.com"})
    assert resp.status_code == 403


def test_register_missing_email_returns_422(client):
    resp = client.post("/v1/users/register", json={})
    assert resp.status_code == 422


def test_onboarding_status_requires_owner_session(client):
    resp = client.get("/v1/onboarding/status")
    assert resp.status_code == 401


def test_request_login_link_unverified_account_does_not_send_email(client):
    client.post("/v1/users/register", json={"email": "unverified@example.com"})

    with patch.object(api_app.state.email_sender, "send_login_email") as send_login_email:
        resp = client.post(
            "/v1/auth/request-login-link",
            json={"email": "unverified@example.com"},
        )

    assert resp.status_code == 202
    send_login_email.assert_not_called()


def test_exchange_login_link_requires_verified_email(client):
    client.post("/v1/users/register", json={"email": "preverify@example.com"})

    store: UserStore = api_app.state.user_store
    token_store: TokenStore = api_app.state.token_store
    owner = store.get_owner_membership_by_email("preverify@example.com")
    assert owner is not None
    raw_token = token_store.issue_owner_login_token(owner.membership_id)

    resp = client.get(f"/v1/auth/exchange-login-link?token={raw_token}")

    assert resp.status_code == 409
    assert "verified" in resp.json()["detail"].lower()


def test_request_and_exchange_login_link_work_after_email_verification(client):
    client.post("/v1/users/register", json={"email": "verified@example.com"})

    store: UserStore = api_app.state.user_store
    token_store: TokenStore = api_app.state.token_store
    owner = store.get_owner_membership_by_email("verified@example.com")
    assert owner is not None

    verify_token = token_store.issue_email_verification_token(owner.membership_id)
    verify_resp = client.get(f"/v1/onboarding/verify-email?token={verify_token}")
    assert verify_resp.status_code == 200

    with patch.object(api_app.state.email_sender, "send_login_email") as send_login_email:
        request_resp = client.post(
            "/v1/auth/request-login-link",
            json={"email": "verified@example.com"},
        )

    assert request_resp.status_code == 202
    send_login_email.assert_called_once()

    login_token = token_store.issue_owner_login_token(owner.membership_id)
    exchange_resp = client.get(f"/v1/auth/exchange-login-link?token={login_token}")

    assert exchange_resp.status_code == 200
    data = exchange_resp.json()
    assert data["status"] == "pending_db_connection"
    assert data["owner_session_token"].startswith("mdbo_")
