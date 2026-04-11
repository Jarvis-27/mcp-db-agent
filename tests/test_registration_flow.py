"""Integration tests for the tenant-backed onboarding flow."""

from unittest.mock import patch

import pytest
from cachetools import TTLCache
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.api.app import api_app
from src.auth.crypto import CredentialCipher
from src.auth.token_store import TokenStore, VerificationToken
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
    token_store = TokenStore(engine, email_token_ttl_minutes=60, login_token_ttl_minutes=30)

    api_app.state.user_store = store
    api_app.state.token_store = token_store
    api_app.state.email_sender = LogEmailSender()
    api_app.state.cipher = cipher
    api_app.state.auth_key_cache = TTLCache(maxsize=100, ttl=60)
    api_app.state.owner_session_cache = TTLCache(maxsize=100, ttl=60)
    api_app.state.factory = None

    from src.api.app import limiter

    limiter._storage.reset()

    with patch.object(ug_module.settings, "environment", "development"), \
         patch("src.api.app.settings") as mock_settings:
        mock_settings.registration_open = True
        mock_settings.allow_sqlite_user_dbs = False
        mock_settings.billing_gate_enabled = False
        mock_settings.mfa_gate_enabled = False
        mock_settings.admin_api_key = "test-admin-key"
        mock_settings.register_rate_limit = "100/minute"
        mock_settings.app_base_url = "http://localhost:8000"
        mock_settings.owner_session_ttl_hours = 24
        yield

    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client():
    return TestClient(api_app, raise_server_exceptions=True)


_VALID_EMAIL = "owner@example.com"
_VALID_PG_URL = "postgresql://user:pass@8.8.8.8/mydb"
_ADMIN_KEY = "test-admin-key"


def _issue_email_token_for_email(email: str) -> tuple[str, str]:
    store: UserStore = api_app.state.user_store
    owner = store.get_owner_membership_by_email(email)
    assert owner is not None
    raw = api_app.state.token_store.issue_email_verification_token(owner.membership_id)
    return owner.tenant_id, raw


def _issue_login_token_for_email(email: str) -> str:
    store: UserStore = api_app.state.user_store
    owner = store.get_owner_membership_by_email(email)
    assert owner is not None
    return api_app.state.token_store.issue_owner_login_token(owner.membership_id)


def test_register_returns_pending_tenant(client):
    resp = client.post("/v1/users/register", json={"email": _VALID_EMAIL, "tenant_name": "Acme"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "pending_email_verification"
    assert "tenant_id" in data


def test_verify_email_returns_owner_session(client):
    client.post("/v1/users/register", json={"email": _VALID_EMAIL})
    tenant_id, raw = _issue_email_token_for_email(_VALID_EMAIL)

    resp = client.get(f"/v1/onboarding/verify-email?token={raw}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tenant_id"] == tenant_id
    assert data["status"] == "pending_db_connection"
    assert data["owner_session_token"].startswith("mdbo_")


def test_full_happy_path(client):
    reg = client.post("/v1/users/register", json={"email": _VALID_EMAIL})
    assert reg.status_code == 201

    tenant_id, raw = _issue_email_token_for_email(_VALID_EMAIL)
    verify = client.get(f"/v1/onboarding/verify-email?token={raw}")
    owner_session = verify.json()["owner_session_token"]

    status = client.get(
        "/v1/onboarding/status",
        headers={"Authorization": f"Bearer {owner_session}"},
    )
    assert status.status_code == 200
    assert status.json()["status"] == "pending_db_connection"

    with patch("socket.getaddrinfo", return_value=[(2, 1, 0, "", ("8.8.8.8", 5432))]), \
         patch("src.api.app._dry_run_connect"):
        db_resp = client.post(
            "/v1/onboarding/database",
            headers={"Authorization": f"Bearer {owner_session}"},
            json={"database_url": _VALID_PG_URL, "name": "primary"},
        )
    assert db_resp.status_code == 200
    assert db_resp.json()["status"] == "pending_review"

    approve = client.post(
        f"/v1/admin/tenants/{tenant_id}/approve",
        headers={"X-Admin-Key": _ADMIN_KEY},
    )
    assert approve.status_code == 200
    assert approve.json()["status"] == "active"

    key_resp = client.post(
        "/v1/api-keys",
        headers={"Authorization": f"Bearer {owner_session}"},
        json={"name": "default", "scopes": ["mcp_read"]},
    )
    assert key_resp.status_code == 201
    api_key = key_resp.json()["api_key"]

    me = client.get("/v1/users/me", headers={"X-API-Key": api_key})
    assert me.status_code == 200
    assert me.json()["tenant_id"] == tenant_id
    assert me.json()["status"] == "active"


def test_login_link_exchange_returns_owner_session(client):
    client.post("/v1/users/register", json={"email": _VALID_EMAIL})
    tenant_id, raw = _issue_email_token_for_email(_VALID_EMAIL)
    client.get(f"/v1/onboarding/verify-email?token={raw}")

    login_token = _issue_login_token_for_email(_VALID_EMAIL)
    resp = client.get(f"/v1/auth/exchange-login-link?token={login_token}")
    assert resp.status_code == 200
    assert resp.json()["tenant_id"] == tenant_id
    assert resp.json()["owner_session_token"].startswith("mdbo_")


def test_request_login_link_is_non_enumerating(client):
    resp = client.post("/v1/auth/request-login-link", json={"email": "missing@example.com"})
    assert resp.status_code == 202
    assert "sent" in resp.json()["message"].lower()
