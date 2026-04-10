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
from src.auth.token_store import TokenStore
from src.auth.user_store import Base, UserStore
from src.email_sender import LogEmailSender


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

    from src.auth.token_store import VerificationToken
    VerificationToken.__table__.create(bind=engine, checkfirst=True)

    key = Fernet.generate_key().decode()
    cipher = CredentialCipher([key])
    store = UserStore(engine, cipher)
    token_store = TokenStore(engine)

    api_app.state.user_store = store
    api_app.state.token_store = token_store
    api_app.state.email_sender = LogEmailSender()
    api_app.state.cipher = cipher
    api_app.state.auth_key_cache = TTLCache(maxsize=100, ttl=60)
    api_app.state.factory = None

    # Reset slowapi limiter storage between tests
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
    return TestClient(api_app, raise_server_exceptions=True)


_VALID_EMAIL = "user@example.com"


def _register(client, email=_VALID_EMAIL):
    """Helper: POST /v1/users/register with email only."""
    return client.post(
        "/v1/users/register",
        json={"email": email},
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
# Bad / missing fields → 422 or 400
# ---------------------------------------------------------------------------


def test_register_missing_email_returns_422(client):
    resp = client.post("/v1/users/register", json={})
    assert resp.status_code == 422


def test_register_extra_field_database_url_rejected(client):
    """database_url is no longer accepted at registration (extra='forbid')."""
    resp = client.post(
        "/v1/users/register",
        json={"email": _VALID_EMAIL, "database_url": "postgresql://x/y"},
    )
    assert resp.status_code == 422


def test_register_duplicate_email_returns_409(client):
    _register(client, email="dup@example.com")
    resp = _register(client, email="dup@example.com")
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Closed registration
# ---------------------------------------------------------------------------


def test_register_closed_returns_403(client):
    with patch("src.api.app.settings") as mock_settings:
        mock_settings.registration_open = False
        mock_settings.register_rate_limit = "100/minute"
        resp = client.post("/v1/users/register", json={"email": _VALID_EMAIL})
    assert resp.status_code == 403


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
# Self-service endpoints (active users): PUT /v1/users/me
# ---------------------------------------------------------------------------


def _make_active_user_with_key(store: UserStore, email: str) -> str:
    """Create a user and fast-path to active state. Returns raw API key."""
    # Use the cipher already wired into app.state so decryption works later
    cipher = api_app.state.cipher
    user_id = store.create_user(email=email)
    store.transition_state(user_id, "pending_db_connection")
    store.set_database_url(user_id, cipher.encrypt("postgresql://user:pass@8.8.8.8/mydb"))
    store.transition_state(user_id, "pending_review")
    return store.issue_first_api_key(user_id)


def test_update_me_sanitizes_dangerous_params_in_url(client):
    """sslkey and similar params must be stripped on URL update."""
    import src.auth.url_guard as ug_module
    store: UserStore = api_app.state.user_store
    # Use the store's cipher for proper encryption
    api_key = _make_active_user_with_key(store, "update@example.com")

    dirty_url = "postgresql://user:pass@8.8.8.8/mydb?sslkey=/etc/ssl/key.pem"
    with patch.object(ug_module.settings, "environment", "development"), \
         patch("src.api.app._dry_run_connect"), \
         patch("socket.getaddrinfo", return_value=[(2, 1, 0, "", ("8.8.8.8", 5432))]):
        resp = client.put(
            "/v1/users/me",
            json={"database_url": dirty_url},
            headers={"X-API-Key": api_key},
        )
    assert resp.status_code == 200
    config = store.get_user_by_api_key(api_key)
    assert config is not None
    assert "sslkey" not in (config.database_url or "")
