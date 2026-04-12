"""Tests for legacy API-key compatibility endpoints under the tenant model."""

from unittest.mock import patch

import pytest
import src.auth.url_guard as ug_module
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

_VALID_PG_URL = "postgresql://user:pass@8.8.8.8/mydb"


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
    api_app.state.cipher = cipher
    api_app.state.token_store = token_store
    api_app.state.email_sender = LogEmailSender()
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
        mock_settings.owner_session_ttl_hours = 24
        yield
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client():
    return TestClient(api_app)


@pytest.fixture
def registered_user():
    """Create an active tenant via the self-serve path (no pending_review)."""
    store: UserStore = api_app.state.user_store
    cipher: CredentialCipher = api_app.state.cipher
    tenant_id, membership_id = store.create_tenant_with_owner(email="test@example.com")
    store.set_email_verified(membership_id)
    store.transition_tenant_state(tenant_id, "pending_db_connection")
    store.upsert_active_database(tenant_id, cipher.encrypt(_VALID_PG_URL))
    store.activate_tenant(tenant_id)  # setup_complete + active + free plan
    api_key, key_row = store.create_api_key(
        tenant_id=tenant_id,
        name="default",
        scopes=["mcp_read"],
        created_by_membership_id=membership_id,
    )
    return {"tenant_id": tenant_id, "api_key": api_key, "api_key_id": str(key_row.id)}


def test_get_me_returns_200(client, registered_user):
    resp = client.get("/v1/users/me", headers={"x-api-key": registered_user["api_key"]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["tenant_id"] == registered_user["tenant_id"]
    assert data["is_active"] is True
    assert data["status"] == "setup_complete"
    assert data["account_status"] == "active"
    assert data["plan_code"] == "free"
    assert data["billing_status"] == "free"


def test_get_me_missing_key_returns_401(client):
    resp = client.get("/v1/users/me")
    assert resp.status_code == 401


def test_put_me_with_empty_body_returns_200(client, registered_user):
    resp = client.put(
        "/v1/users/me",
        headers={"x-api-key": registered_user["api_key"]},
        json={},
    )
    assert resp.status_code == 200


def test_rotate_key_issues_new_key(client, registered_user):
    old_key = registered_user["api_key"]
    resp = client.post("/v1/users/me/rotate-key", headers={"x-api-key": old_key})
    assert resp.status_code == 200
    new_key = resp.json()["api_key"]
    assert new_key != old_key
    assert new_key.startswith("mdbk_")
    assert api_app.state.user_store.count_active_api_keys(registered_user["tenant_id"]) == 1


def test_rotate_key_old_key_returns_401(client, registered_user):
    old_key = registered_user["api_key"]
    resp = client.post("/v1/users/me/rotate-key", headers={"x-api-key": old_key})
    assert resp.status_code == 200
    api_app.state.auth_key_cache.clear()
    me = client.get("/v1/users/me", headers={"x-api-key": old_key})
    assert me.status_code == 401


def test_delete_me_returns_410(client, registered_user):
    key = registered_user["api_key"]
    resp = client.delete("/v1/users/me", headers={"x-api-key": key})
    assert resp.status_code == 410


def test_bearer_token_accepted_on_me(client, registered_user):
    key = registered_user["api_key"]
    resp = client.get("/v1/users/me", headers={"authorization": f"Bearer {key}"})
    assert resp.status_code == 200
