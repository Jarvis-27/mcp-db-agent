"""API tests for the explicit MCP OAuth account-linking flow."""

from __future__ import annotations

from unittest.mock import patch

from cachetools import TTLCache
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from src.api.app import api_app
from src.auth.crypto import CredentialCipher
from src.auth.oauth_verifier import OAuthClaims
from src.auth.token_store import TokenStore
from src.auth.user_store import Base, UserStore
from src.email_sender import LogEmailSender


def _register_and_get_session(client: TestClient, email: str) -> tuple[str, str]:
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


class _FakeTokenResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, str]:
        return {"access_token": "oauth.jwt.token"}


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, url: str, data: dict) -> _FakeTokenResponse:
        assert url == "https://issuer.example.com/oauth/token"
        assert data["grant_type"] == "authorization_code"
        assert data["client_id"] == "client_123"
        assert data["redirect_uri"] == "http://localhost:8000/api/v1/account/mcp-oauth/callback"
        assert data["code"] == "oauth-code"
        assert data["code_verifier"]
        return _FakeTokenResponse()


def _claims() -> OAuthClaims:
    return OAuthClaims(
        issuer="https://issuer.example.com",
        subject="oauth2|abc123",
        scopes=frozenset({"openid", "email", "profile"}),
        expires_at=2_000_000_000,
        email="oauth@example.com",
        audience=("https://api.example.com/mcp",),
    )


@patch("src.api.app.settings")
def test_oauth_link_start_and_callback_link_user(mock_settings):
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

    mock_settings.registration_open = True
    mock_settings.allow_sqlite_user_dbs = False
    mock_settings.billing_gate_enabled = False
    mock_settings.mfa_gate_enabled = False
    mock_settings.register_rate_limit = "100/minute"
    mock_settings.app_base_url = "http://localhost:8000"
    mock_settings.frontend_base_url = "http://localhost:3000"
    mock_settings.user_session_ttl_hours = 24
    mock_settings.oauth_is_configured.return_value = True
    mock_settings.oauth_link_is_configured.return_value = True
    mock_settings.oauth_issuer_url = "https://issuer.example.com/"
    mock_settings.oauth_client_id = "client_123"
    mock_settings.oauth_client_secret = ""
    mock_settings.oauth_link_redirect_uri = "http://localhost:8000/api/v1/account/mcp-oauth/callback"
    mock_settings.oauth_audience = "https://api.example.com/mcp"
    mock_settings.oauth_jwks_url = ""
    mock_settings.oauth_jwks_cache_seconds = 300
    mock_settings.oauth_http_timeout_seconds = 10

    client = TestClient(api_app)
    user_id, session_token = _register_and_get_session(client, "oauth-link@example.com")

    start = client.post(
        "/v1/account/mcp-oauth/start",
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert start.status_code == 200, start.text
    start_data = start.json()
    assert "https://issuer.example.com/authorize?" in start_data["authorization_url"]
    assert start_data["state"]

    with (
        patch("httpx.AsyncClient", _FakeAsyncClient),
        patch("src.auth.oauth_verifier.OAuthVerifier.verify", return_value=_claims()),
    ):
        callback = client.get(
            "/v1/account/mcp-oauth/callback",
            params={"code": "oauth-code", "state": start_data["state"]},
            follow_redirects=False,
        )

    assert callback.status_code == 302
    assert callback.headers["location"] == "http://localhost:3000/setup/clients?oauth=linked"

    status = store.get_oauth_link_status(user_id)
    assert status is not None
    assert status.linked is True
    assert status.oauth_email == "oauth@example.com"


@patch("src.api.app.settings")
def test_oauth_link_callback_rejects_invalid_state(mock_settings):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    cipher = CredentialCipher([Fernet.generate_key().decode()])

    api_app.state.user_store = UserStore(engine, cipher)
    api_app.state.cipher = cipher
    api_app.state.token_store = TokenStore(engine)
    api_app.state.email_sender = LogEmailSender()
    api_app.state.auth_key_cache = TTLCache(maxsize=100, ttl=60)
    api_app.state.user_session_cache = TTLCache(maxsize=100, ttl=60)
    api_app.state.factory = None

    from src.api.app import limiter

    limiter._storage.reset()

    mock_settings.oauth_link_is_configured.return_value = True
    mock_settings.frontend_base_url = "http://localhost:3000"

    client = TestClient(api_app)
    resp = client.get(
        "/v1/account/mcp-oauth/callback",
        params={"code": "oauth-code", "state": "bad-state"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert (
        resp.headers["location"]
        == "http://localhost:3000/setup/clients?oauth_error=invalid_state"
    )
