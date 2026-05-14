"""Tests for /v1/account (API-key-authenticated) and key rotation."""

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
        mock_settings.static_outbound_ip = ""
        yield
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client():
    return TestClient(api_app)


@pytest.fixture
def registered_user(client):
    """Create an active user via the self-serve path; returns user info dict."""
    # Sign up
    reg = client.post("/v1/auth/signup", json={"email": "test@example.com"})
    assert reg.status_code == 201
    user_id = reg.json()["user_id"]

    # Verify email
    store: UserStore = api_app.state.user_store
    token_store: TokenStore = api_app.state.token_store
    ctx = store.get_user_by_email("test@example.com")
    raw_token = token_store.issue_email_verification_token(ctx.user_id)
    verify = client.get(f"/v1/auth/verify-email?token={raw_token}")
    session_token = verify.json()["session_token"]

    # Activate (connect DB)
    with (
        patch("socket.getaddrinfo", return_value=[(2, 1, 0, "", ("8.8.8.8", 5432))]),
        patch("src.api.app._dry_run_connect"),
    ):
        client.put(
            "/v1/account/database",
            headers={"Authorization": f"Bearer {session_token}"},
            json={"database_url": _VALID_PG_URL, "name": "primary"},
        )

    # Create API key
    resp = client.post(
        "/v1/account/api-keys",
        headers={"Authorization": f"Bearer {session_token}"},
        json={"name": "default", "scopes": ["mcp_read"]},
    )
    assert resp.status_code == 201
    api_key = resp.json()["api_key"]
    api_key_id = resp.json()["id"]

    return {
        "user_id": user_id,
        "session_token": session_token,
        "api_key": api_key,
        "api_key_id": api_key_id,
    }


def test_get_account_returns_200(client, registered_user):
    # GET /v1/account is session-authenticated (same as all other /account/* routes)
    resp = client.get(
        "/v1/account",
        headers={"x-session-token": registered_user["session_token"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == registered_user["user_id"]
    assert data["is_active"] is True
    assert data["status"] == "setup_complete"
    assert data["account_status"] == "active"
    assert data["plan_code"] == "free"
    assert data["billing_status"] == "free"


def test_get_account_missing_session_returns_401(client):
    resp = client.get("/v1/account")
    assert resp.status_code == 401


def test_get_database_metadata_returns_safe_connection_summary(client, registered_user):
    resp = client.get(
        "/v1/account/database",
        headers={"x-session-token": registered_user["session_token"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data == {
        "name": "primary",
        "db_type": "postgresql",
        "connected": True,
        "host": "8.8.8.8",
        "database_name": "mydb",
        "last_validated_at": data["last_validated_at"],
    }
    assert data["last_validated_at"] is not None
    assert "pass" not in resp.text
    assert "postgresql://user" not in resp.text


def test_validate_database_connection_rechecks_stored_connection(client, registered_user):
    with (
        patch("socket.getaddrinfo", return_value=[(2, 1, 0, "", ("8.8.8.8", 5432))]),
        patch("src.api.app._dry_run_connect") as dry_run,
    ):
        resp = client.post(
            "/v1/account/database/validate",
            headers={"x-session-token": registered_user["session_token"]},
        )

    assert resp.status_code == 200
    dry_run.assert_called_once()
    data = resp.json()
    assert data["connected"] is True
    assert data["host"] == "8.8.8.8"
    assert data["database_name"] == "mydb"


def test_bearer_session_token_accepted_on_account(client, registered_user):
    token = registered_user["session_token"]
    resp = client.get("/v1/account", headers={"authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_rotate_key_issues_new_key(client, registered_user):
    old_key = registered_user["api_key"]
    api_key_id = registered_user["api_key_id"]
    session_token = registered_user["session_token"]

    resp = client.post(
        f"/v1/account/api-keys/{api_key_id}/rotate",
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert resp.status_code == 200
    new_key = resp.json()["api_key"]
    assert new_key != old_key
    assert new_key.startswith("mdbk_")
    store: UserStore = api_app.state.user_store
    assert store.count_active_api_keys(registered_user["user_id"]) == 1


def test_rotate_key_old_key_returns_401(client, registered_user):
    old_key = registered_user["api_key"]
    api_key_id = registered_user["api_key_id"]
    session_token = registered_user["session_token"]

    resp = client.post(
        f"/v1/account/api-keys/{api_key_id}/rotate",
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert resp.status_code == 200
    # Clear cache so next request hits the store
    api_app.state.auth_key_cache.clear()
    me = client.get("/v1/account", headers={"x-api-key": old_key})
    assert me.status_code == 401


def test_list_api_keys(client, registered_user):
    session_token = registered_user["session_token"]
    resp = client.get(
        "/v1/account/api-keys",
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert resp.status_code == 200
    keys = resp.json()
    assert len(keys) == 1
    assert keys[0]["id"] == registered_user["api_key_id"]


def test_revoke_api_key(client, registered_user):
    session_token = registered_user["session_token"]
    api_key_id = registered_user["api_key_id"]

    resp = client.delete(
        f"/v1/account/api-keys/{api_key_id}",
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert resp.status_code == 204
    # Clear cache and verify old key is gone
    api_app.state.auth_key_cache.clear()
    me = client.get("/v1/account", headers={"x-api-key": registered_user["api_key"]})
    assert me.status_code == 401


# ---------------------------------------------------------------------------
# Static outbound IP surfacing
# ---------------------------------------------------------------------------


def test_account_status_static_outbound_ip_default_null(client, registered_user):
    resp = client.get(
        "/v1/account/status",
        headers={"x-session-token": registered_user["session_token"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "static_outbound_ip" in data
    assert data["static_outbound_ip"] is None


def test_account_status_returns_configured_static_outbound_ip(client, registered_user):
    import src.api.app as app_module

    with patch.object(app_module.settings, "static_outbound_ip", "203.0.113.42"):
        resp = client.get(
            "/v1/account/status",
            headers={"x-session-token": registered_user["session_token"]},
        )

    assert resp.status_code == 200
    assert resp.json()["static_outbound_ip"] == "203.0.113.42"


# ---------------------------------------------------------------------------
# _dry_run_connect error shape
# ---------------------------------------------------------------------------


def test_dry_run_connect_network_error_returns_network_unreachable_code():
    import pytest
    from fastapi import HTTPException

    from src.api import app as app_module

    def _raise_timeout(*_args, **_kwargs):
        raise OSError("connection timed out")

    with patch("src.api.app.create_engine", side_effect=_raise_timeout):
        with pytest.raises(HTTPException) as exc_info:
            app_module._dry_run_connect("postgresql://u:p@h/d")

    assert exc_info.value.status_code == 400
    assert isinstance(exc_info.value.detail, dict)
    assert exc_info.value.detail["code"] == "network_unreachable"
    assert "firewall" in exc_info.value.detail["message"].lower()


def test_dry_run_connect_auth_error_returns_connection_failed_code():
    import pytest
    from fastapi import HTTPException

    from src.api import app as app_module

    def _raise_auth(*_args, **_kwargs):
        raise OSError("FATAL: password authentication failed for user")

    with patch("src.api.app.create_engine", side_effect=_raise_auth):
        with pytest.raises(HTTPException) as exc_info:
            app_module._dry_run_connect("postgresql://u:p@h/d")

    assert exc_info.value.status_code == 400
    assert isinstance(exc_info.value.detail, dict)
    assert exc_info.value.detail["code"] == "connection_failed"
    assert "credentials" in exc_info.value.detail["message"].lower()
