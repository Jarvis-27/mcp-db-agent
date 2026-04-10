"""Tests for POST /v1/users/register and GET /v1/onboarding/status."""

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
    import src.auth.url_guard as ug_module

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
    # Treat all tests as development so the SSL-mode requirement doesn't block
    # clean test URLs. Production SSL enforcement is tested in test_url_guard.py.
    with patch.object(ug_module.settings, "environment", "development"):
        yield
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client():
    return TestClient(api_app, raise_server_exceptions=True)


_VALID_PG_URL = "postgresql://user:pass@8.8.8.8/mydb"
_VALID_EMAIL = "user@example.com"


def _mock_resolved():
    import socket
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 5432))]


def _register(client, email=_VALID_EMAIL, database_url=_VALID_PG_URL):
    """Helper: POST /v1/users/register with mocked network calls."""
    with patch("socket.getaddrinfo", return_value=_mock_resolved()), \
         patch("src.api.app._dry_run_connect"):
        return client.post(
            "/v1/users/register",
            json={"email": email, "database_url": database_url},
        )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_register_returns_201_pending(client):
    resp = _register(client)
    assert resp.status_code == 201
    data = resp.json()
    assert "user_id" in data
    assert data["status"] == "pending_email_verification"
    assert "message" in data
    # No API key should be in the response
    assert "api_key" not in data


def test_register_stores_user_as_inactive(client):
    resp = _register(client)
    assert resp.status_code == 201
    user_id = resp.json()["user_id"]
    store: UserStore = api_app.state.user_store
    # The user exists but has no key and is inactive
    status = store.get_onboarding_status(user_id)
    assert status == "pending_email_verification"
    # No key means get_user_by_api_key returns None for any key
    assert store.get_user_by_api_key("mdbk_anything") is None


def test_register_email_is_stored(client):
    resp = _register(client, email="test@example.com")
    assert resp.status_code == 201
    user_id = resp.json()["user_id"]
    store: UserStore = api_app.state.user_store
    config = store.get_user_by_id(user_id)
    assert config is not None
    assert config.email == "test@example.com"


# ---------------------------------------------------------------------------
# Bad URL → 400
# ---------------------------------------------------------------------------


def test_register_bad_url_returns_400(client):
    with patch("socket.getaddrinfo", return_value=_mock_resolved()), \
         patch("src.api.app._dry_run_connect"):
        resp = client.post(
            "/v1/users/register",
            json={"email": _VALID_EMAIL, "database_url": "sqlite:///./evil.db"},
        )
    assert resp.status_code == 400


def test_register_ssrf_url_returns_400(client):
    with patch("socket.getaddrinfo", return_value=[(2, 1, 0, "", ("169.254.169.254", 5432))]):
        resp = client.post(
            "/v1/users/register",
            json={"email": _VALID_EMAIL, "database_url": "postgresql://x@metadata-host/y"},
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
            json={"email": _VALID_EMAIL, "database_url": _VALID_PG_URL},
        )
    assert resp.status_code == 400
    assert "connect" in resp.json()["detail"].lower()


def test_register_missing_email_returns_422(client):
    """email field is now required."""
    with patch("socket.getaddrinfo", return_value=_mock_resolved()), \
         patch("src.api.app._dry_run_connect"):
        resp = client.post(
            "/v1/users/register",
            json={"database_url": _VALID_PG_URL},
        )
    assert resp.status_code == 422


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
# Onboarding status endpoint
# ---------------------------------------------------------------------------


def test_onboarding_status_returns_pending(client):
    resp = _register(client)
    user_id = resp.json()["user_id"]

    status_resp = client.get(f"/v1/onboarding/status?user_id={user_id}")
    assert status_resp.status_code == 200
    data = status_resp.json()
    assert data["user_id"] == user_id
    assert data["status"] == "pending_email_verification"
    assert "next_step" in data
    assert len(data["next_step"]) > 0


def test_onboarding_status_unknown_user_returns_404(client):
    resp = client.get("/v1/onboarding/status?user_id=does-not-exist")
    assert resp.status_code == 404


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


# ---------------------------------------------------------------------------
# Sanitization — dangerous query params must not survive registration
# ---------------------------------------------------------------------------


def test_register_sanitizes_dangerous_params_in_url(client):
    """passfile and similar params must be stripped before persistence."""
    dirty_url = "postgresql://user:pass@8.8.8.8/mydb?passfile=/etc/passwd"
    with patch("socket.getaddrinfo", return_value=_mock_resolved()), \
         patch("src.api.app._dry_run_connect"):
        resp = client.post(
            "/v1/users/register",
            json={"email": _VALID_EMAIL, "database_url": dirty_url},
        )
    assert resp.status_code == 201
    user_id = resp.json()["user_id"]
    store: UserStore = api_app.state.user_store
    # Activate the user so we can look them up
    raw_key = store.issue_first_api_key(user_id)
    config = store.get_user_by_api_key(raw_key)
    assert config is not None
    assert "passfile" not in config.database_url


def test_update_me_sanitizes_dangerous_params_in_url(client):
    """sslkey and similar params must be stripped on URL update."""
    resp = _register(client)
    assert resp.status_code == 201
    user_id = resp.json()["user_id"]
    store: UserStore = api_app.state.user_store
    api_key = store.issue_first_api_key(user_id)

    dirty_url = "postgresql://user:pass@8.8.8.8/mydb?sslkey=/etc/ssl/key.pem"
    with patch("socket.getaddrinfo", return_value=_mock_resolved()), \
         patch("src.api.app._dry_run_connect"):
        resp = client.put(
            "/v1/users/me",
            json={"database_url": dirty_url},
            headers={"X-API-Key": api_key},
        )
    assert resp.status_code == 200
    config = store.get_user_by_api_key(api_key)
    assert config is not None
    assert "sslkey" not in config.database_url
