"""Tests for the operator-only /v1/admin/* endpoints."""

from datetime import UTC, datetime, timedelta
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
from src.core.query_log import QueryLog
from src.email_sender import LogEmailSender

_VALID_PG_URL = "postgresql://user:pass@8.8.8.8/mydb"
_ADMIN_EMAIL = "admin@example.com"


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
    query_log = QueryLog(engine=engine)

    api_app.state.user_store = store
    api_app.state.cipher = cipher
    api_app.state.token_store = token_store
    api_app.state.email_sender = LogEmailSender()
    api_app.state.auth_key_cache = TTLCache(maxsize=100, ttl=60)
    api_app.state.user_session_cache = TTLCache(maxsize=100, ttl=60)
    api_app.state.factory = None
    api_app.state.query_log = query_log

    from src.api.app import limiter

    limiter._storage.reset()
    with (
        patch.object(ug_module.settings, "environment", "development"),
        patch("src.api.app.settings") as mock_settings,
        patch("src.api.admin.settings") as admin_settings,
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

        admin_settings.admin_emails_set.return_value = {_ADMIN_EMAIL}
        yield
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client():
    return TestClient(api_app)


def _register_and_verify(client, email: str) -> dict[str, str]:
    """Walk a user through signup → email verify → DB connect → API key."""
    reg = client.post("/v1/auth/signup", json={"email": email})
    assert reg.status_code == 201, reg.text
    user_id = reg.json()["user_id"]

    store: UserStore = api_app.state.user_store
    token_store: TokenStore = api_app.state.token_store
    ctx = store.get_user_by_email(email)
    raw_token = token_store.issue_email_verification_token(ctx.user_id)
    verify = client.get(f"/v1/auth/verify-email?token={raw_token}")
    session_token = verify.json()["session_token"]

    with (
        patch("socket.getaddrinfo", return_value=[(2, 1, 0, "", ("8.8.8.8", 5432))]),
        patch("src.api.app._dry_run_connect"),
    ):
        client.put(
            "/v1/account/database",
            headers={"Authorization": f"Bearer {session_token}"},
            json={"database_url": _VALID_PG_URL, "name": "primary"},
        )

    keys_resp = client.post(
        "/v1/account/api-keys",
        headers={"Authorization": f"Bearer {session_token}"},
        json={"name": "default", "scopes": ["mcp_read"]},
    )
    assert keys_resp.status_code == 201, keys_resp.text
    api_key_id = keys_resp.json()["id"]
    return {
        "user_id": user_id,
        "session_token": session_token,
        "api_key": keys_resp.json()["api_key"],
        "api_key_id": api_key_id,
    }


@pytest.fixture
def admin_user(client):
    return _register_and_verify(client, _ADMIN_EMAIL)


@pytest.fixture
def regular_user(client):
    return _register_and_verify(client, "regular@example.com")


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------


def test_admin_me_missing_session_returns_401(client):
    resp = client.get("/v1/admin/me")
    assert resp.status_code == 401


def test_admin_me_denies_non_admin_email(client, regular_user):
    resp = client.get(
        "/v1/admin/me",
        headers={"x-session-token": regular_user["session_token"]},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Admin privileges required"


def test_admin_me_allows_listed_email(client, admin_user):
    resp = client.get(
        "/v1/admin/me",
        headers={"x-session-token": admin_user["session_token"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_admin"] is True
    assert data["email"] == _ADMIN_EMAIL
    assert data["user_id"] == admin_user["user_id"]
    assert data["grants"] == [{"scope": "operator"}]


def test_admin_me_case_insensitive_match(client):
    # Admin allowlist contains lowercase; signup also lowercases. Verify mixed-
    # case configuration (e.g. ADMIN_EMAILS=Admin@Example.com) still matches.
    from src.api import admin as admin_module

    admin_module.settings.admin_emails_set.return_value = {"admin@example.com"}
    user = _register_and_verify(client, "Admin@Example.com")  # email normalized to lowercase

    resp = client.get(
        "/v1/admin/me",
        headers={"x-session-token": user["session_token"]},
    )
    assert resp.status_code == 200


def test_admin_overview_denied_for_non_admin(client, regular_user):
    resp = client.get(
        "/v1/admin/overview",
        headers={"x-session-token": regular_user["session_token"]},
    )
    assert resp.status_code == 403


def test_admin_users_denied_for_non_admin(client, regular_user):
    resp = client.get(
        "/v1/admin/users",
        headers={"x-session-token": regular_user["session_token"]},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


def test_admin_overview_returns_zero_state_when_no_queries(client, admin_user):
    resp = client.get(
        "/v1/admin/overview",
        headers={"x-session-token": admin_user["session_token"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["queries_today"] == 0
    assert data["error_rate_today"] == 0.0
    assert data["p50_duration_ms_today"] is None
    assert data["p95_duration_ms_today"] is None
    assert len(data["daily_query_counts"]) == 14
    assert data["users_total"] >= 1
    assert "active" in data["users_by_status"]


def test_admin_overview_counts_by_status(client, admin_user, regular_user):
    store: UserStore = api_app.state.user_store
    # Suspend the regular user
    store.set_account_status(regular_user["user_id"], "suspended")

    resp = client.get(
        "/v1/admin/overview",
        headers={"x-session-token": admin_user["session_token"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["users_by_status"]["suspended"] == 1
    assert data["users_by_status"]["active"] == 1
    assert data["users_by_status"]["closed"] == 0


def test_admin_overview_error_rate(client, admin_user, regular_user):
    query_log: QueryLog = api_app.state.query_log
    for i in range(3):
        query_log.log_query(
            question="q",
            sql="SELECT 1",
            success=True,
            row_count=1,
            attempts=1,
            duration_ms=50 + i,
            error=None,
            user_id=regular_user["user_id"],
            api_key_id=None,
        )
    query_log.log_query(
        question="q",
        sql="bad",
        success=False,
        row_count=0,
        attempts=1,
        duration_ms=10,
        error="boom",
        user_id=regular_user["user_id"],
        api_key_id=None,
    )

    resp = client.get(
        "/v1/admin/overview",
        headers={"x-session-token": admin_user["session_token"]},
    )
    data = resp.json()
    assert data["queries_today"] == 4
    assert data["error_rate_today"] == pytest.approx(0.25)
    assert data["p50_duration_ms_today"] is not None
    assert data["p95_duration_ms_today"] is not None


# ---------------------------------------------------------------------------
# Users list
# ---------------------------------------------------------------------------


def test_admin_users_filters_by_q_email_substring(client, admin_user, regular_user):
    resp = client.get(
        "/v1/admin/users?q=regular",
        headers={"x-session-token": admin_user["session_token"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["email"] == "regular@example.com"


def test_admin_users_filters_by_status(client, admin_user, regular_user):
    store: UserStore = api_app.state.user_store
    store.set_account_status(regular_user["user_id"], "suspended")

    resp = client.get(
        "/v1/admin/users?status=suspended",
        headers={"x-session-token": admin_user["session_token"]},
    )
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["account_status"] == "suspended"


def test_admin_users_pagination_total_independent_of_limit(client, admin_user, regular_user):
    resp = client.get(
        "/v1/admin/users?limit=1",
        headers={"x-session-token": admin_user["session_token"]},
    )
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 1
    assert data["limit"] == 1
    assert data["offset"] == 0


def test_admin_users_last_query_at_null_when_no_history(client, admin_user, regular_user):
    resp = client.get(
        "/v1/admin/users?q=regular",
        headers={"x-session-token": admin_user["session_token"]},
    )
    item = resp.json()["items"][0]
    assert item["last_query_at"] is None


def test_admin_users_last_query_at_populated_after_log(client, admin_user, regular_user):
    query_log: QueryLog = api_app.state.query_log
    query_log.log_query(
        question="q",
        sql="SELECT 1",
        success=True,
        row_count=1,
        attempts=1,
        duration_ms=10,
        error=None,
        user_id=regular_user["user_id"],
        api_key_id=None,
    )
    resp = client.get(
        "/v1/admin/users?q=regular",
        headers={"x-session-token": admin_user["session_token"]},
    )
    item = resp.json()["items"][0]
    assert item["last_query_at"] is not None


# ---------------------------------------------------------------------------
# User detail
# ---------------------------------------------------------------------------


def test_admin_user_detail_returns_404_for_unknown_id(client, admin_user):
    resp = client.get(
        "/v1/admin/users/no-such-user",
        headers={"x-session-token": admin_user["session_token"]},
    )
    assert resp.status_code == 404


def test_admin_user_detail_omits_db_url_enc(client, admin_user, regular_user):
    resp = client.get(
        f"/v1/admin/users/{regular_user['user_id']}",
        headers={"x-session-token": admin_user["session_token"]},
    )
    assert resp.status_code == 200
    body = resp.text
    assert "db_url_enc" not in body
    assert "postgresql://user" not in body
    assert "pass@" not in body
    data = resp.json()
    assert data["db_name"] == "primary"
    assert data["db_validation_status"] == "validated"


def test_admin_user_detail_includes_api_keys_and_recent_queries(client, admin_user, regular_user):
    query_log: QueryLog = api_app.state.query_log
    query_log.log_query(
        question="hello",
        sql="SELECT 1",
        success=True,
        row_count=1,
        attempts=1,
        duration_ms=15,
        error=None,
        user_id=regular_user["user_id"],
        api_key_id=regular_user["api_key_id"],
    )

    resp = client.get(
        f"/v1/admin/users/{regular_user['user_id']}",
        headers={"x-session-token": admin_user["session_token"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["api_keys"]) == 1
    assert data["api_keys"][0]["id"] == regular_user["api_key_id"]
    assert data["api_keys"][0]["revoked_at"] is None
    assert len(data["recent_queries"]) == 1
    assert data["recent_queries"][0]["question"] == "hello"


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------


def test_admin_suspend_sets_status_and_busts_cache(client, admin_user, regular_user):
    # Prime the session cache so we can verify it is busted
    cache = api_app.state.user_session_cache
    initial = client.get(
        "/v1/account/status",
        headers={"x-session-token": regular_user["session_token"]},
    )
    assert initial.status_code == 200
    assert len(cache) > 0

    resp = client.post(
        f"/v1/admin/users/{regular_user['user_id']}/suspend",
        headers={"x-session-token": admin_user["session_token"]},
        json={"reason": "spammy queries"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["account_status"] == "suspended"
    assert data["suspended_at"] is not None
    # Cache no longer contains the regular user's session entry
    for value in list(cache.values()):
        assert value.user_id != regular_user["user_id"]


def test_admin_suspend_already_suspended_returns_409(client, admin_user, regular_user):
    client.post(
        f"/v1/admin/users/{regular_user['user_id']}/suspend",
        headers={"x-session-token": admin_user["session_token"]},
        json={},
    )
    resp = client.post(
        f"/v1/admin/users/{regular_user['user_id']}/suspend",
        headers={"x-session-token": admin_user["session_token"]},
        json={},
    )
    assert resp.status_code == 409


def test_admin_unsuspend_clears_status(client, admin_user, regular_user):
    client.post(
        f"/v1/admin/users/{regular_user['user_id']}/suspend",
        headers={"x-session-token": admin_user["session_token"]},
        json={},
    )
    resp = client.post(
        f"/v1/admin/users/{regular_user['user_id']}/unsuspend",
        headers={"x-session-token": admin_user["session_token"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["account_status"] == "active"


def test_admin_unsuspend_when_not_suspended_returns_409(client, admin_user, regular_user):
    resp = client.post(
        f"/v1/admin/users/{regular_user['user_id']}/unsuspend",
        headers={"x-session-token": admin_user["session_token"]},
    )
    assert resp.status_code == 409


def test_admin_close_revokes_keys_and_sessions(client, admin_user, regular_user):
    resp = client.post(
        f"/v1/admin/users/{regular_user['user_id']}/close",
        headers={"x-session-token": admin_user["session_token"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["account_status"] == "closed"
    assert data["closed_at"] is not None

    store: UserStore = api_app.state.user_store
    keys = store.list_api_keys(regular_user["user_id"])
    assert all(k.revoked_at is not None for k in keys)

    # Subsequent session-authed request from the closed user fails because
    # get_user_by_session returns None for non-active accounts.
    # The cache was busted, so the next call goes to the store and fails.
    api_app.state.user_session_cache.clear()
    follow = client.get(
        "/v1/account/status",
        headers={"x-session-token": regular_user["session_token"]},
    )
    assert follow.status_code == 401


def test_admin_close_is_terminal(client, admin_user, regular_user):
    client.post(
        f"/v1/admin/users/{regular_user['user_id']}/close",
        headers={"x-session-token": admin_user["session_token"]},
    )
    resp = client.post(
        f"/v1/admin/users/{regular_user['user_id']}/close",
        headers={"x-session-token": admin_user["session_token"]},
    )
    assert resp.status_code == 409


def test_admin_suspend_closed_user_returns_409(client, admin_user, regular_user):
    client.post(
        f"/v1/admin/users/{regular_user['user_id']}/close",
        headers={"x-session-token": admin_user["session_token"]},
    )
    resp = client.post(
        f"/v1/admin/users/{regular_user['user_id']}/suspend",
        headers={"x-session-token": admin_user["session_token"]},
        json={},
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# API key revoke
# ---------------------------------------------------------------------------


def test_admin_revoke_api_key_succeeds(client, admin_user, regular_user):
    resp = client.post(
        f"/v1/admin/users/{regular_user['user_id']}/api-keys/{regular_user['api_key_id']}/revoke",
        headers={"x-session-token": admin_user["session_token"]},
    )
    assert resp.status_code == 204
    store: UserStore = api_app.state.user_store
    keys = store.list_api_keys(regular_user["user_id"])
    assert keys[0].revoked_at is not None


def test_admin_revoke_api_key_invalid_user_returns_404(client, admin_user, regular_user):
    resp = client.post(
        f"/v1/admin/users/no-such-user/api-keys/{regular_user['api_key_id']}/revoke",
        headers={"x-session-token": admin_user["session_token"]},
    )
    assert resp.status_code == 404


def test_admin_revoke_api_key_already_revoked_returns_404(client, admin_user, regular_user):
    client.post(
        f"/v1/admin/users/{regular_user['user_id']}/api-keys/{regular_user['api_key_id']}/revoke",
        headers={"x-session-token": admin_user["session_token"]},
    )
    resp = client.post(
        f"/v1/admin/users/{regular_user['user_id']}/api-keys/{regular_user['api_key_id']}/revoke",
        headers={"x-session-token": admin_user["session_token"]},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Cross-user query log
# ---------------------------------------------------------------------------


def _seed_queries(user_id: str, api_key_id: str | None = None) -> None:
    query_log: QueryLog = api_app.state.query_log
    query_log.log_query(
        question="ok",
        sql="SELECT 1",
        success=True,
        row_count=1,
        attempts=1,
        duration_ms=12,
        error=None,
        user_id=user_id,
        api_key_id=api_key_id,
    )
    query_log.log_query(
        question="bad",
        sql="select * from nope",
        success=False,
        row_count=0,
        attempts=1,
        duration_ms=5,
        error="no such table",
        user_id=user_id,
        api_key_id=api_key_id,
        error_code="undefined_table",
    )


def test_admin_queries_filters_by_user_id(client, admin_user, regular_user):
    _seed_queries(regular_user["user_id"])
    _seed_queries(admin_user["user_id"])
    resp = client.get(
        f"/v1/admin/queries?user_id={regular_user['user_id']}",
        headers={"x-session-token": admin_user["session_token"]},
    )
    data = resp.json()
    assert data["total"] == 2
    for item in data["items"]:
        assert item["user_id"] == regular_user["user_id"]
        assert item["user_email"] == "regular@example.com"


def test_admin_queries_filters_by_success_false(client, admin_user, regular_user):
    _seed_queries(regular_user["user_id"])
    resp = client.get(
        "/v1/admin/queries?success=false",
        headers={"x-session-token": admin_user["session_token"]},
    )
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["success"] is False


def test_admin_queries_filters_by_error_code(client, admin_user, regular_user):
    _seed_queries(regular_user["user_id"])
    resp = client.get(
        "/v1/admin/queries?error_code=undefined_table",
        headers={"x-session-token": admin_user["session_token"]},
    )
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["error_code"] == "undefined_table"


def test_admin_queries_invalid_since_returns_400(client, admin_user):
    resp = client.get(
        "/v1/admin/queries?since=not-a-date",
        headers={"x-session-token": admin_user["session_token"]},
    )
    assert resp.status_code == 400


def test_admin_queries_filters_by_since(client, admin_user, regular_user):
    _seed_queries(regular_user["user_id"])
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    resp = client.get(
        "/v1/admin/queries",
        params={"since": future},
        headers={"x-session-token": admin_user["session_token"]},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 0


def test_admin_queries_pagination(client, admin_user, regular_user):
    for _ in range(3):
        _seed_queries(regular_user["user_id"])
    resp = client.get(
        f"/v1/admin/queries?user_id={regular_user['user_id']}&limit=2",
        headers={"x-session-token": admin_user["session_token"]},
    )
    data = resp.json()
    assert data["total"] == 6
    assert len(data["items"]) == 2
    assert data["limit"] == 2
