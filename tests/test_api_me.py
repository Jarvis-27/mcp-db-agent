"""Tests for GET/PUT/DELETE /v1/users/me and POST /v1/users/me/rotate-key."""

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


def _mock_resolve():
    import socket
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 5432))]


@pytest.fixture(autouse=True)
def app_state():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    key = Fernet.generate_key().decode()
    cipher = CredentialCipher([key])
    store = UserStore(engine, cipher)

    from src.auth.token_store import VerificationToken
    VerificationToken.__table__.create(bind=engine, checkfirst=True)
    token_store = TokenStore(engine)

    api_app.state.user_store = store
    api_app.state.cipher = cipher
    api_app.state.token_store = token_store
    api_app.state.email_sender = LogEmailSender()
    api_app.state.auth_key_cache = TTLCache(maxsize=100, ttl=60)
    api_app.state.factory = None
    # Reset slowapi limiter storage so tests don't interfere with each other
    from src.api.app import limiter

    limiter._storage.reset()
    # Treat all tests as development so the SSL-mode requirement doesn't block
    # clean test URLs. Production SSL enforcement is tested in test_url_guard.py.
    with patch.object(ug_module.settings, "environment", "development"), \
         patch("src.api.app.settings") as mock_settings:
        mock_settings.registration_open = True
        mock_settings.allow_sqlite_user_dbs = False
        mock_settings.billing_gate_enabled = False
        mock_settings.mfa_gate_enabled = False
        mock_settings.admin_api_key = "test-admin-key"
        mock_settings.register_rate_limit = "100/minute"
        mock_settings.app_base_url = "http://localhost:8000"
        yield
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client():
    return TestClient(api_app)


@pytest.fixture
def registered_user(client):
    """Register a user and fast-path them to active so they have an API key."""
    resp = client.post("/v1/users/register", json={"email": "test@example.com"})
    assert resp.status_code == 201
    user_id = resp.json()["user_id"]
    # Fast-path to active: advance state machine, set DB URL, issue key
    store: UserStore = api_app.state.user_store
    cipher: CredentialCipher = api_app.state.cipher
    store.transition_state(user_id, "pending_db_connection")
    store.set_database_url(user_id, cipher.encrypt(_VALID_PG_URL))
    store.transition_state(user_id, "pending_review")
    api_key = store.issue_first_api_key(user_id)
    return {"user_id": user_id, "api_key": api_key}


# ---------------------------------------------------------------------------
# GET /v1/users/me
# ---------------------------------------------------------------------------


def test_get_me_returns_200(client, registered_user):
    resp = client.get("/v1/users/me", headers={"x-api-key": registered_user["api_key"]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == registered_user["user_id"]
    assert data["is_active"] is True


def test_get_me_missing_key_returns_401(client):
    resp = client.get("/v1/users/me")
    assert resp.status_code == 401


def test_get_me_invalid_key_returns_401(client):
    resp = client.get("/v1/users/me", headers={"x-api-key": "mdbk_wrong"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PUT /v1/users/me
# ---------------------------------------------------------------------------


def test_put_me_with_empty_body_returns_200(client, registered_user):
    # PUT with no fields is a no-op update (only refreshes updated_at).
    # LLM provider is server-owned and cannot be changed per-user.
    resp = client.put(
        "/v1/users/me",
        headers={"x-api-key": registered_user["api_key"]},
        json={},
    )
    assert resp.status_code == 200


def test_put_me_bad_url_returns_400(client, registered_user):
    resp = client.put(
        "/v1/users/me",
        headers={"x-api-key": registered_user["api_key"]},
        json={"database_url": "sqlite:///./evil.db"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /v1/users/me/rotate-key
# ---------------------------------------------------------------------------


def test_rotate_key_issues_new_key(client, registered_user):
    old_key = registered_user["api_key"]
    resp = client.post(
        "/v1/users/me/rotate-key", headers={"x-api-key": old_key}
    )
    assert resp.status_code == 200
    new_key = resp.json()["api_key"]
    assert new_key != old_key
    assert new_key.startswith("mdbk_")


def test_rotate_key_old_key_returns_401(client, registered_user):
    old_key = registered_user["api_key"]
    resp = client.post("/v1/users/me/rotate-key", headers={"x-api-key": old_key})
    assert resp.status_code == 200

    # Old key must now be rejected (cache is cleared in rotate_key endpoint)
    # Clear cache to simulate next request after cache TTL
    api_app.state.auth_key_cache.clear()

    me = client.get("/v1/users/me", headers={"x-api-key": old_key})
    assert me.status_code == 401


def test_rotate_key_new_key_works(client, registered_user):
    old_key = registered_user["api_key"]
    resp = client.post("/v1/users/me/rotate-key", headers={"x-api-key": old_key})
    new_key = resp.json()["api_key"]

    me = client.get("/v1/users/me", headers={"x-api-key": new_key})
    assert me.status_code == 200


# ---------------------------------------------------------------------------
# DELETE /v1/users/me
# ---------------------------------------------------------------------------


def test_delete_me_deactivates_user(client, registered_user):
    key = registered_user["api_key"]
    resp = client.delete("/v1/users/me", headers={"x-api-key": key})
    assert resp.status_code == 204

    # Subsequent requests must fail (cache is cleared by delete endpoint)
    api_app.state.auth_key_cache.clear()
    me = client.get("/v1/users/me", headers={"x-api-key": key})
    assert me.status_code == 401


# ---------------------------------------------------------------------------
# Bearer token also works
# ---------------------------------------------------------------------------


def test_bearer_token_accepted_on_me(client, registered_user):
    key = registered_user["api_key"]
    resp = client.get(
        "/v1/users/me", headers={"authorization": f"Bearer {key}"}
    )
    assert resp.status_code == 200
