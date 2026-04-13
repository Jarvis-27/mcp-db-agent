"""Tests for GET /v1/dashboard/summary and GET /v1/usage/recent endpoints."""

from unittest.mock import patch

import src.auth.url_guard as ug_module
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
from src.core.query_log import QueryLog
from src.email_sender import LogEmailSender

_VALID_PG_URL = "postgresql://user:pass@8.8.8.8/mydb"


def _register_and_get_owner_session(client: TestClient, email: str) -> tuple[str, str]:
    reg = client.post("/v1/users/register", json={"email": email})
    assert reg.status_code == 201

    store: UserStore = api_app.state.user_store
    token_store: TokenStore = api_app.state.token_store
    owner = store.get_owner_membership_by_email(email)
    raw_token = token_store.issue_email_verification_token(owner.membership_id)
    verify = client.get(f"/v1/onboarding/verify-email?token={raw_token}")
    assert verify.status_code == 200
    return reg.json()["tenant_id"], verify.json()["owner_session_token"]


def _activate_tenant(client: TestClient, owner_session: str) -> None:
    with (
        patch("socket.getaddrinfo", return_value=[(2, 1, 0, "", ("8.8.8.8", 5432))]),
        patch("src.api.app._dry_run_connect"),
    ):
        resp = client.post(
            "/v1/onboarding/database",
            headers={"Authorization": f"Bearer {owner_session}"},
            json={"database_url": _VALID_PG_URL, "name": "primary"},
        )
    assert resp.status_code == 200


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
    query_log = QueryLog(engine)

    api_app.state.user_store = store
    api_app.state.cipher = cipher
    api_app.state.token_store = token_store
    api_app.state.email_sender = LogEmailSender()
    api_app.state.auth_key_cache = TTLCache(maxsize=100, ttl=60)
    api_app.state.owner_session_cache = TTLCache(maxsize=100, ttl=60)
    api_app.state.factory = None
    api_app.state.query_log = query_log

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
        mock_settings.frontend_base_url = "http://localhost:3000"
        mock_settings.owner_session_ttl_hours = 24
        yield
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client():
    return TestClient(api_app, raise_server_exceptions=True)


# ── Dashboard summary tests ────────────────────────────────────────────────────


def test_dashboard_summary_requires_auth(client):
    """Missing owner session → 401."""
    resp = client.get("/v1/dashboard/summary")
    assert resp.status_code == 401


def test_dashboard_summary_active_tenant(client):
    """Active tenant with a connected database gets a complete summary."""
    _, owner_session = _register_and_get_owner_session(client, "dash@example.com")
    _activate_tenant(client, owner_session)

    resp = client.get(
        "/v1/dashboard/summary",
        headers={"Authorization": f"Bearer {owner_session}"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["account_status"] == "active"
    assert data["onboarding_status"] == "setup_complete"
    assert data["plan_code"] == "free"
    assert data["billing_status"] == "free"

    # Active database was connected during activation
    assert data["active_database"] is not None
    assert data["active_database"]["name"] == "primary"
    assert data["active_database"]["validation_status"] == "validated"

    # Quota fields
    quota = data["quota"]
    assert quota["daily_limit"] == 25  # FREE_PLAN limit
    assert quota["daily_used"] == 0
    assert quota["daily_remaining"] == 25
    assert quota["warning_level"] is None
    assert "reset_at" in quota


def test_dashboard_summary_no_database_shows_null(client):
    """Tenant who has verified email but not yet connected a DB gets active_database=null."""
    _, owner_session = _register_and_get_owner_session(client, "nodbyet@example.com")

    resp = client.get(
        "/v1/dashboard/summary",
        headers={"Authorization": f"Bearer {owner_session}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["active_database"] is None
    assert data["api_key_count"] == 0


# ── Usage recent tests ─────────────────────────────────────────────────────────


def test_usage_recent_requires_auth(client):
    """Missing owner session → 401."""
    resp = client.get("/v1/usage/recent")
    assert resp.status_code == 401


def test_usage_recent_empty(client):
    """New tenant with no queries returns empty items list."""
    _, owner_session = _register_and_get_owner_session(client, "noqueries@example.com")

    resp = client.get(
        "/v1/usage/recent",
        headers={"Authorization": f"Bearer {owner_session}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


def test_usage_recent_respects_limit(client):
    """Limit query param caps number of items returned."""
    tenant_id, owner_session = _register_and_get_owner_session(client, "limitme@example.com")
    _activate_tenant(client, owner_session)

    # Log 5 synthetic queries directly
    query_log: QueryLog = api_app.state.query_log
    for i in range(5):
        query_log.log_query(
            question=f"question {i}",
            sql=f"SELECT {i}",
            success=True,
            row_count=1,
            attempts=1,
            duration_ms=10,
            error=None,
            tenant_id=tenant_id,
            api_key_id=None,
        )

    resp = client.get(
        "/v1/usage/recent?limit=3",
        headers={"Authorization": f"Bearer {owner_session}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 3
    assert data["total"] == 3

    # Verify item fields
    item = data["items"][0]
    assert "id" in item
    assert "timestamp" in item
    assert "question" in item
    assert "success" in item
