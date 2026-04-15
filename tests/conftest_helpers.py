"""Shared helpers for API integration tests."""
from unittest.mock import patch

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


def make_app_state(with_query_log: bool = False):
    """Return (engine, store, token_store, cipher, ctx_manager) for use in fixtures."""
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

    if with_query_log:
        from src.core.query_log import QueryLog
        api_app.state.query_log = QueryLog(engine)

    return engine, store, token_store, cipher


def mock_settings():
    return {
        "registration_open": True,
        "allow_sqlite_user_dbs": False,
        "billing_gate_enabled": False,
        "mfa_gate_enabled": False,
        "register_rate_limit": "100/minute",
        "app_base_url": "http://localhost:8000",
        "frontend_base_url": "http://localhost:3000",
        "user_session_ttl_hours": 24,
    }


def register_and_get_session(client: TestClient, email: str) -> tuple[str, str]:
    """Sign up and return (user_id, session_token) after email verification."""
    reg = client.post("/v1/auth/signup", json={"email": email})
    assert reg.status_code == 201, reg.text
    user_id = reg.json()["user_id"]

    store: UserStore = api_app.state.user_store
    token_store: TokenStore = api_app.state.token_store
    raw_token = token_store.issue_email_verification_token(user_id)
    verify = client.get(f"/v1/auth/verify-email?token={raw_token}")
    assert verify.status_code == 200, verify.text
    return user_id, verify.json()["session_token"]


def activate_via_api(client: TestClient, session_token: str) -> None:
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


def create_api_key(client: TestClient, session_token: str, name: str = "default") -> str:
    resp = client.post(
        "/v1/account/api-keys",
        headers={"Authorization": f"Bearer {session_token}"},
        json={"name": name, "scopes": ["mcp_read"]},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["api_key"]
