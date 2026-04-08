"""Tests for POST /v1/users/register."""

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def app_state(tmp_path):
    """Wire up app.state with in-memory store, cipher, and cache."""
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
    # Reset slowapi limiter storage between tests
    from src.api.app import limiter

    limiter._storage.reset()
    yield
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client():
    return TestClient(api_app, raise_server_exceptions=True)


_VALID_PG_URL = "postgresql://user:pass@8.8.8.8/mydb"


def _mock_resolved():
    import socket
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 5432))]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_register_returns_201_with_api_key(client):
    with patch("socket.getaddrinfo", return_value=_mock_resolved()), \
         patch("src.api.app._dry_run_connect"):
        resp = client.post(
            "/v1/users/register",
            json={"database_url": _VALID_PG_URL, "llm_provider": "anthropic"},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["api_key"].startswith("mdbk_")
    assert "user_id" in data
    assert "warning" in data


def test_register_stores_user(client):
    with patch("socket.getaddrinfo", return_value=_mock_resolved()), \
         patch("src.api.app._dry_run_connect"):
        resp = client.post(
            "/v1/users/register",
            json={"database_url": _VALID_PG_URL, "llm_provider": "groq"},
        )
    assert resp.status_code == 201
    # Verify the user can authenticate
    api_key = resp.json()["api_key"]
    store: UserStore = api_app.state.user_store
    config = store.get_user_by_api_key(api_key)
    assert config is not None
    assert config.llm_provider == "groq"


# ---------------------------------------------------------------------------
# Bad URL → 400
# ---------------------------------------------------------------------------


def test_register_bad_url_returns_400(client):
    resp = client.post(
        "/v1/users/register",
        json={"database_url": "sqlite:///./evil.db"},
    )
    assert resp.status_code == 400


def test_register_ssrf_url_returns_400(client):
    with patch("socket.getaddrinfo", return_value=[(2, 1, 0, "", ("169.254.169.254", 5432))]):
        resp = client.post(
            "/v1/users/register",
            json={"database_url": "postgresql://x@metadata-host/y"},
        )
    assert resp.status_code == 400


def test_register_dry_run_failure_returns_400(client):
    from fastapi import HTTPException

    def failing_connect(url, timeout=5):
        raise HTTPException(
            status_code=400,
            detail="Could not connect to the provided database.",
        )

    with patch("socket.getaddrinfo", return_value=_mock_resolved()), \
         patch("src.api.app._dry_run_connect", side_effect=failing_connect):
        resp = client.post(
            "/v1/users/register",
            json={"database_url": _VALID_PG_URL},
        )
    assert resp.status_code == 400
    assert "connect" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Oversize body → 413
# ---------------------------------------------------------------------------


def test_register_oversize_body_rejected(client):
    from src.middleware.body_size import BodySizeLimitMiddleware
    from starlette.testclient import TestClient as StarletteClient

    app_with_limit = BodySizeLimitMiddleware(api_app, max_bytes=10)
    sc = StarletteClient(app_with_limit)
    resp = sc.post(
        "/v1/users/register",
        content=b"x" * 100,
        headers={"content-length": "100", "content-type": "application/json"},
    )
    assert resp.status_code == 413


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health_live(client):
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_ready(client):
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
