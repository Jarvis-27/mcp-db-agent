"""Focused tests for tenant admin endpoints and admin-key access control."""

from unittest.mock import patch

import pytest
from cachetools import TTLCache
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from src.api.app import api_app
from src.auth.crypto import CredentialCipher
from src.auth.onboarding import (
    ACCOUNT_ACTIVE,
    ACCOUNT_CLOSED,
    ACCOUNT_RESTRICTED,
    ACCOUNT_SUSPENDED,
)
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

    with patch("src.api.app.settings") as mock_settings:
        mock_settings.admin_api_key = "correct-admin-key"
        mock_settings.registration_open = True
        mock_settings.billing_gate_enabled = False
        mock_settings.mfa_gate_enabled = False
        mock_settings.register_rate_limit = "100/minute"
        mock_settings.app_base_url = "http://localhost:8000"
        mock_settings.allow_sqlite_user_dbs = False
        mock_settings.owner_session_ttl_hours = 24
        yield

    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client():
    return TestClient(api_app, raise_server_exceptions=True)


def _make_active_tenant(email: str = "owner@example.com") -> str:
    """Create a fully activated tenant via the self-serve path."""
    store: UserStore = api_app.state.user_store
    cipher = api_app.state.cipher
    tenant_id, membership_id = store.create_tenant_with_owner(email=email)
    store.set_email_verified(membership_id)
    store.transition_tenant_state(tenant_id, "pending_db_connection")
    store.upsert_active_database(tenant_id, cipher.encrypt("postgresql://user:pass@8.8.8.8/mydb"))
    store.activate_tenant(tenant_id)
    return tenant_id


def _make_restricted_tenant(email: str = "risk@example.com") -> str:
    """Create an active tenant then place it under an admin risk hold."""
    store: UserStore = api_app.state.user_store
    tenant_id = _make_active_tenant(email=email)
    store.set_account_status(tenant_id, ACCOUNT_RESTRICTED)
    return tenant_id


def test_missing_admin_key_returns_403(client):
    resp = client.post("/v1/admin/tenants/some-id/approve")
    assert resp.status_code == 403


def test_wrong_admin_key_returns_403(client):
    resp = client.post(
        "/v1/admin/tenants/some-id/approve",
        headers={"X-Admin-Key": "wrong-key"},
    )
    assert resp.status_code == 403


def test_list_pending_returns_restricted_tenants(client):
    """Admin /pending endpoint lists tenants with account_status=restricted."""
    tenant_id = _make_restricted_tenant()
    resp = client.get(
        "/v1/admin/tenants/pending",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    assert resp.status_code == 200
    returned_ids = {item["tenant_id"] for item in resp.json()}
    assert tenant_id in returned_ids


def test_list_pending_does_not_include_active_tenants(client):
    active_id = _make_active_tenant(email="active@example.com")
    _make_restricted_tenant(email="restricted@example.com")
    resp = client.get(
        "/v1/admin/tenants/pending",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    assert resp.status_code == 200
    returned_ids = {item["tenant_id"] for item in resp.json()}
    assert active_id not in returned_ids


def test_approve_restricted_tenant_returns_active(client):
    tenant_id = _make_restricted_tenant()
    resp = client.post(
        f"/v1/admin/tenants/{tenant_id}/approve",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["account_status"] == ACCOUNT_ACTIVE
    assert data["tenant_id"] == tenant_id


def test_approve_already_active_tenant_returns_409(client):
    tenant_id = _make_active_tenant()
    resp = client.post(
        f"/v1/admin/tenants/{tenant_id}/approve",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    assert resp.status_code == 409


def test_suspend_active_tenant(client):
    tenant_id = _make_active_tenant()
    resp = client.post(
        f"/v1/admin/tenants/{tenant_id}/suspend",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    assert resp.status_code == 200
    assert resp.json()["account_status"] == ACCOUNT_SUSPENDED


def test_approve_suspended_tenant_reactivates(client):
    tenant_id = _make_active_tenant()
    client.post(
        f"/v1/admin/tenants/{tenant_id}/suspend",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    resp = client.post(
        f"/v1/admin/tenants/{tenant_id}/approve",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    assert resp.status_code == 200
    assert resp.json()["account_status"] == ACCOUNT_ACTIVE


def test_close_active_tenant(client):
    tenant_id = _make_active_tenant()
    resp = client.post(
        f"/v1/admin/tenants/{tenant_id}/close",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    assert resp.status_code == 200
    assert resp.json()["account_status"] == ACCOUNT_CLOSED


def test_close_is_terminal(client):
    tenant_id = _make_active_tenant()
    client.post(
        f"/v1/admin/tenants/{tenant_id}/close",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    resp = client.post(
        f"/v1/admin/tenants/{tenant_id}/close",
        headers={"X-Admin-Key": "correct-admin-key"},
    )
    assert resp.status_code == 409
