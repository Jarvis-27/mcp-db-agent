"""API tests for setup payload generation."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import src.auth.url_guard as ug_module
import pytest
from cachetools import TTLCache
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.api.app import api_app
from src.auth.crypto import CredentialCipher
from src.auth.token_store import TokenStore
from src.auth.user_store import Base, UserStore
from src.email_sender import LogEmailSender

_VALID_PG_URL = "postgresql://user:pass@8.8.8.8/mydb"


def _register_and_get_session(client: TestClient, email: str) -> tuple[str, str]:
    """Register a user and return (user_id, session_token) after email verify."""
    reg = client.post("/v1/auth/signup", json={"email": email})
    assert reg.status_code == 201, reg.text

    store: UserStore = api_app.state.user_store
    token_store: TokenStore = api_app.state.token_store
    ctx = store.get_user_by_email(email)
    assert ctx is not None
    raw_token = token_store.issue_email_verification_token(ctx.user_id)
    verify = client.get(f"/v1/auth/verify-email?token={raw_token}")
    assert verify.status_code == 200, verify.text
    return reg.json()["user_id"], verify.json()["session_token"]


def _activate_via_api(client: TestClient, session_token: str) -> None:
    with (
        patch("socket.getaddrinfo", return_value=[(2, 1, 0, "", ("8.8.8.8", 5432))]),
        patch("src.api.app._dry_run_connect"),
    ):
        resp = client.put(
            "/v1/account/database",
            headers={"Authorization": f"Bearer {session_token}"},
            json={"database_url": _VALID_PG_URL, "name": "primary"},
        )
    assert resp.status_code == 200, resp.text


def _create_api_key(client: TestClient, session_token: str, name: str = "default") -> str:
    resp = client.post(
        "/v1/account/api-keys",
        headers={"Authorization": f"Bearer {session_token}"},
        json={"name": name, "scopes": ["mcp_read"]},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["api_key"]


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
        mock_settings.mcp_auth_mode = "api_key_only"
        mock_settings.oauth_is_configured.return_value = False
        mock_settings.oauth_link_is_configured.return_value = False
        yield
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client():
    return TestClient(api_app)


def test_setup_payload_requires_session(client):
    resp = client.post("/v1/account/setup-payloads", json={})
    assert resp.status_code == 401


def test_setup_payload_returns_user_scoped_payload_and_no_secret_leaks(client):
    user_id, session_token = _register_and_get_session(client, "setup@example.com")
    _activate_via_api(client, session_token)
    raw_key = _create_api_key(client, session_token)

    resp = client.post(
        "/v1/account/setup-payloads",
        headers={"Authorization": f"Bearer {session_token}"},
        json={"raw_api_key": raw_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    payload_text = resp.text

    assert data["user_id"] == user_id
    assert data["mcp_url"] == "http://localhost:8000/mcp"
    assert data["plan_code"] == "free"
    assert data["mcp_auth_mode"] == "api_key_only"
    assert data["oauth_enabled_for_mcp"] is False
    assert data["api_keys_enabled_for_mcp"] is True
    assert data["quota_summary"]["daily_limit"] == 25
    assert data["api_key_state"]["raw_key_included"] is True
    assert data["api_key_state"]["requires_manual_key_entry"] is False
    assert raw_key in data["clients"]["vs_code"]["snippet"]
    assert "postgresql://user:pass@8.8.8.8/mydb" not in payload_text
    assert "key_hash" not in payload_text
    assert "session_token" not in payload_text
    assert data["clients"]["chatgpt_developer_mode"]["status"] == "unsupported_until_oauth"


def test_setup_payload_uses_placeholders_when_raw_key_not_supplied(client):
    _user_id, session_token = _register_and_get_session(client, "placeholder@example.com")
    _activate_via_api(client, session_token)
    raw_key = _create_api_key(client, session_token)

    resp = client.post(
        "/v1/account/setup-payloads",
        headers={"Authorization": f"Bearer {session_token}"},
        json={},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["api_key_state"]["raw_key_included"] is False
    assert data["api_key_state"]["requires_manual_key_entry"] is True
    assert raw_key not in resp.text
    assert "${input:mcpDbAgentApiKey}" in data["clients"]["vs_code"]["snippet"]
    assert "${env:MCP_DB_AGENT_API_KEY}" in data["clients"]["cursor"]["snippet"]


def test_setup_payload_rejects_revoked_key(client):
    user_id, session_token = _register_and_get_session(client, "revoked@example.com")
    _activate_via_api(client, session_token)
    raw_key = _create_api_key(client, session_token)

    store: UserStore = api_app.state.user_store
    active = next(row for row in store.list_api_keys(user_id) if row.revoked_at is None)
    assert store.revoke_api_key(user_id, str(active.id)) is True

    resp = client.post(
        "/v1/account/setup-payloads",
        headers={"Authorization": f"Bearer {session_token}"},
        json={"raw_api_key": raw_key},
    )
    assert resp.status_code == 400
    assert "does not match an active api key" in resp.json()["detail"].lower()


def test_setup_payload_returns_placeholder_after_revoke(client):
    user_id, session_token = _register_and_get_session(client, "after-revoke@example.com")
    _activate_via_api(client, session_token)
    _raw_key = _create_api_key(client, session_token)

    store: UserStore = api_app.state.user_store
    active = next(row for row in store.list_api_keys(user_id) if row.revoked_at is None)
    assert store.revoke_api_key(user_id, str(active.id)) is True

    resp = client.post(
        "/v1/account/setup-payloads",
        headers={"Authorization": f"Bearer {session_token}"},
        json={},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["api_key_state"]["active_key_count"] == 0
    assert data["api_key_state"]["selected_api_key_id"] is None
    assert data["api_key_state"]["raw_key_included"] is False
    assert data["api_key_state"]["requires_manual_key_entry"] is True
    assert "<paste-api-key-here>" in data["clients"]["generic_http"]["snippet"]


def test_setup_payload_returns_409_before_setup_complete(client):
    _user_id, session_token = _register_and_get_session(client, "incomplete@example.com")

    resp = client.post(
        "/v1/account/setup-payloads",
        headers={"Authorization": f"Bearer {session_token}"},
        json={},
    )
    assert resp.status_code == 409
    assert "setup must be complete" in resp.json()["detail"].lower()


def test_setup_payload_reports_live_pro_quota(client):
    user_id, session_token = _register_and_get_session(client, "pro@example.com")
    _activate_via_api(client, session_token)

    store: UserStore = api_app.state.user_store
    next_reset = datetime.now(UTC) + timedelta(hours=2)
    with store._engine.connect() as conn:
        conn.execute(
            text(
                "UPDATE users SET plan_code = 'pro', daily_query_count = 120,"
                " daily_quota_reset_at = :reset WHERE id = :id"
            ),
            {"reset": next_reset, "id": user_id},
        )
        conn.commit()

    resp = client.post(
        "/v1/account/setup-payloads",
        headers={"Authorization": f"Bearer {session_token}"},
        json={},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["plan_code"] == "pro"
    assert data["quota_summary"]["daily_limit"] == 500
    assert data["quota_summary"]["daily_used"] == 120
    assert data["quota_summary"]["daily_remaining"] == 380
    assert data["quota_summary"]["reset_at"] == next_reset.isoformat()


def test_setup_payload_prefers_oauth_templates_in_hybrid_mode(client):
    _user_id, session_token = _register_and_get_session(client, "oauth-hybrid@example.com")
    _activate_via_api(client, session_token)

    with patch("src.api.app.settings") as mock_settings:
        mock_settings.registration_open = True
        mock_settings.allow_sqlite_user_dbs = False
        mock_settings.billing_gate_enabled = False
        mock_settings.mfa_gate_enabled = False
        mock_settings.register_rate_limit = "100/minute"
        mock_settings.app_base_url = "http://localhost:8000"
        mock_settings.frontend_base_url = "http://localhost:3000"
        mock_settings.user_session_ttl_hours = 24
        mock_settings.mcp_auth_mode = "hybrid"
        mock_settings.oauth_is_configured.return_value = True
        mock_settings.oauth_link_is_configured.return_value = True

        resp = client.post(
            "/v1/account/setup-payloads",
            headers={"Authorization": f"Bearer {session_token}"},
            json={},
        )

    assert resp.status_code == 200
    data = resp.json()

    assert data["mcp_auth_mode"] == "hybrid"
    assert data["oauth_enabled_for_mcp"] is True
    assert data["oauth_link_enabled"] is True
    assert data["clients"]["chatgpt_developer_mode"]["status"] == "ready"
    assert data["clients"]["vs_code"]["auth_method"] == "oauth_2_1"
    assert data["clients"]["cursor"]["auth_method"] == "oauth_2_1"
    assert (
        data["clients"]["generic_http"]["auth_method"]
        == "caller_supplied_bearer_token"
    )
