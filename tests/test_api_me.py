"""Tests for GET/PUT/DELETE /v1/users/me and POST /v1/users/me/rotate-key."""

from unittest.mock import patch

import pytest
from cachetools import TTLCache
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from src.api.app import api_app
from src.auth.crypto import CredentialCipher
from src.auth.user_store import Base, UserStore

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
    api_app.state.user_store = store
    api_app.state.auth_key_cache = TTLCache(maxsize=100, ttl=60)
    api_app.state.factory = None
    # Reset slowapi limiter storage so tests don't interfere with each other
    from src.api.app import limiter

    limiter._storage.reset()
    yield
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client():
    return TestClient(api_app)


@pytest.fixture
def registered_user(client):
    with patch("socket.getaddrinfo", return_value=_mock_resolve()), \
         patch("src.api.app._dry_run_connect"):
        resp = client.post(
            "/v1/users/register",
            json={"database_url": _VALID_PG_URL, "llm_provider": "anthropic"},
        )
    assert resp.status_code == 201
    return resp.json()  # {user_id, api_key, warning}


# ---------------------------------------------------------------------------
# GET /v1/users/me
# ---------------------------------------------------------------------------


def test_get_me_returns_200(client, registered_user):
    resp = client.get("/v1/users/me", headers={"x-api-key": registered_user["api_key"]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == registered_user["user_id"]
    assert data["llm_provider"] == "anthropic"
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


def test_put_me_updates_llm_provider(client, registered_user):
    resp = client.put(
        "/v1/users/me",
        headers={"x-api-key": registered_user["api_key"]},
        json={"llm_provider": "groq"},
    )
    assert resp.status_code == 200

    # Verify the change persisted
    me = client.get("/v1/users/me", headers={"x-api-key": registered_user["api_key"]})
    assert me.json()["llm_provider"] == "groq"


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
