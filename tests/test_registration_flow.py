"""Integration tests for the tenant-backed onboarding flow."""

from unittest.mock import patch

import pytest
from cachetools import TTLCache
from cryptography.fernet import Fernet
from fastapi import HTTPException
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
    import src.auth.url_guard as ug_module

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


def test_happy_path_self_serve_activation(client):
    """Full self-serve lifecycle: register → verify → connect DB → active (no admin step)."""
    # 1. Register
    reg = client.post("/v1/users/register", json={"email": "user@example.com"})
    assert reg.status_code == 201
    tenant_id = reg.json()["tenant_id"]
    assert reg.json()["status"] == "pending_email_verification"

    # 2. Retrieve the verification token directly from the token store
    token_store: TokenStore = api_app.state.token_store
    store: UserStore = api_app.state.user_store
    owner = store.get_owner_membership_by_email("user@example.com")
    assert owner is not None
    raw_token = token_store.issue_email_verification_token(owner.membership_id)

    # 3. Verify email
    verify = client.get(f"/v1/onboarding/verify-email?token={raw_token}")
    assert verify.status_code == 200
    owner_session = verify.json()["owner_session_token"]
    assert verify.json()["status"] == "pending_db_connection"

    # 4. Check onboarding status
    status = client.get(
        "/v1/onboarding/status",
        headers={"Authorization": f"Bearer {owner_session}"},
    )
    assert status.status_code == 200
    assert status.json()["status"] == "pending_db_connection"

    # 5. Submit database — expect automatic activation (no admin review)
    with (
        patch("socket.getaddrinfo", return_value=[(2, 1, 0, "", ("8.8.8.8", 5432))]),
        patch("src.api.app._dry_run_connect"),
    ):
        db_resp = client.post(
            "/v1/onboarding/database",
            headers={"Authorization": f"Bearer {owner_session}"},
            json={"database_url": _VALID_PG_URL, "name": "primary"},
        )
    assert db_resp.status_code == 200
    data = db_resp.json()
    # Phase 1 invariant: db submission goes to setup_complete, not pending_review.
    assert data["status"] == "setup_complete"
    assert data["account_status"] == "active"
    assert data["plan_code"] == "free"
    assert data["tenant_id"] == tenant_id

    # 6. Verify onboarding status shows active + setup_complete
    final_status = client.get(
        "/v1/onboarding/status",
        headers={"Authorization": f"Bearer {owner_session}"},
    )
    assert final_status.status_code == 200
    assert final_status.json()["status"] == "setup_complete"
    assert final_status.json()["account_status"] == "active"
    assert final_status.json()["can_issue_api_key"] is True
    assert final_status.json()["blockers"] == []


def test_no_admin_approval_required_on_happy_path(client):
    """Confirm that a tenant reaches setup_complete without any admin endpoint being called."""
    reg = client.post("/v1/users/register", json={"email": "nonadmin@example.com"})
    assert reg.status_code == 201

    store: UserStore = api_app.state.user_store
    token_store: TokenStore = api_app.state.token_store
    owner = store.get_owner_membership_by_email("nonadmin@example.com")
    raw_token = token_store.issue_email_verification_token(owner.membership_id)

    verify = client.get(f"/v1/onboarding/verify-email?token={raw_token}")
    owner_session = verify.json()["owner_session_token"]

    with (
        patch("socket.getaddrinfo", return_value=[(2, 1, 0, "", ("8.8.8.8", 5432))]),
        patch("src.api.app._dry_run_connect"),
    ):
        db_resp = client.post(
            "/v1/onboarding/database",
            headers={"Authorization": f"Bearer {owner_session}"},
            json={"database_url": _VALID_PG_URL},
        )
    assert db_resp.status_code == 200
    # Directly active — no pending_review state was ever reached.
    assert db_resp.json()["status"] == "setup_complete"
    assert db_resp.json()["account_status"] == "active"


# ---------------------------------------------------------------------------
# Phase 2: failure cases
# ---------------------------------------------------------------------------


def _register_and_get_owner_session(client) -> tuple[str, str]:
    """Register a user and return (tenant_id, owner_session_token) after email verify."""
    reg = client.post("/v1/users/register", json={"email": "flow@example.com"})
    assert reg.status_code == 201
    tenant_id = reg.json()["tenant_id"]

    store: UserStore = api_app.state.user_store
    token_store: TokenStore = api_app.state.token_store
    owner = store.get_owner_membership_by_email("flow@example.com")
    raw_token = token_store.issue_email_verification_token(owner.membership_id)

    verify = client.get(f"/v1/onboarding/verify-email?token={raw_token}")
    assert verify.status_code == 200
    return tenant_id, verify.json()["owner_session_token"]


def test_invalid_verification_token_returns_400(client):
    """A bogus verification token is rejected with 400."""
    resp = client.get("/v1/onboarding/verify-email?token=mdbkv_doesnotexist")
    assert resp.status_code == 400
    assert "invalid" in resp.json()["detail"].lower()


def test_already_used_verification_token_returns_400(client):
    """Reusing a verification token returns 400."""
    store: UserStore = api_app.state.user_store
    token_store: TokenStore = api_app.state.token_store

    client.post("/v1/users/register", json={"email": "reuse@example.com"})
    owner = store.get_owner_membership_by_email("reuse@example.com")
    raw_token = token_store.issue_email_verification_token(owner.membership_id)

    # First use succeeds.
    first = client.get(f"/v1/onboarding/verify-email?token={raw_token}")
    assert first.status_code == 200

    # Second use is rejected.
    second = client.get(f"/v1/onboarding/verify-email?token={raw_token}")
    assert second.status_code == 400
    assert "already been used" in second.json()["detail"].lower()


def test_invalid_database_url_returns_400(client):
    """A URL with a blocked scheme is rejected with 400 before any connection attempt."""
    _tenant_id, owner_session = _register_and_get_owner_session(client)
    resp = client.post(
        "/v1/onboarding/database",
        headers={"Authorization": f"Bearer {owner_session}"},
        json={"database_url": "sqlite:///./local.db"},
    )
    assert resp.status_code == 400


def test_unreachable_database_returns_400(client):
    """When the live connectivity check fails, the endpoint returns 400."""
    _tenant_id, owner_session = _register_and_get_owner_session(client)

    def _fail_connect(url, timeout=5):
        raise HTTPException(
            status_code=400,
            detail="Could not connect to the provided database.",
        )

    with (
        patch("socket.getaddrinfo", return_value=[(2, 1, 0, "", ("8.8.8.8", 5432))]),
        patch("src.api.app._dry_run_connect", side_effect=_fail_connect),
    ):
        resp = client.post(
            "/v1/onboarding/database",
            headers={"Authorization": f"Bearer {owner_session}"},
            json={"database_url": _VALID_PG_URL},
        )
    assert resp.status_code == 400
    assert "connect" in resp.json()["detail"].lower()


def test_inactive_tenant_cannot_create_api_key(client):
    """A tenant that hasn't completed setup cannot create an API key (returns 409)."""
    _tenant_id, owner_session = _register_and_get_owner_session(client)
    # Tenant is now in pending_db_connection — setup not complete, no active DB.
    resp = client.post(
        "/v1/api-keys",
        headers={"Authorization": f"Bearer {owner_session}"},
        json={"name": "early-key", "scopes": ["mcp_read"]},
    )
    assert resp.status_code == 409
    assert "not eligible" in resp.json()["detail"].lower()
