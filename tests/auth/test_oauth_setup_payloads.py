"""Tests for auth-mode-aware setup payload generation."""

from __future__ import annotations

from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from src.auth.crypto import CredentialCipher
from src.auth.user_store import Base, UserStore
from src.setup.service import SetupPayloadService

_VALID_URL = "postgresql://user:pass@8.8.8.8/appdb"


def _make_store() -> UserStore:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return UserStore(engine, CredentialCipher([Fernet.generate_key().decode()]))


def _activate_user(store: UserStore) -> str:
    uid = store.create_user("test@example.com")
    store.set_email_verified(uid)
    store.transition_user_state(uid, "pending_db_connection")
    store.upsert_user_database(uid, store._cipher.encrypt(_VALID_URL))
    store.activate_user(uid)
    return uid


def test_api_key_only_mode_keeps_chatgpt_unavailable_even_if_oauth_is_configured():
    store = _make_store()
    uid = _activate_user(store)
    payload = SetupPayloadService(
        store,
        app_base_url="http://localhost:8000",
        mcp_auth_mode="api_key_only",
        oauth_configured=True,
    ).build_payload(uid)

    assert payload.mcp_auth_mode == "api_key_only"
    assert payload.oauth_enabled_for_mcp is False
    assert payload.api_keys_enabled_for_mcp is True
    assert payload.chatgpt_developer_mode.status == "unsupported_until_oauth"
    assert payload.vs_code.auth_method == "bearer_api_key"
    assert payload.cursor.auth_method == "bearer_api_key"
    assert payload.generic_http.auth_method == "bearer_api_key"


def test_hybrid_mode_prefers_oauth_for_supported_clients():
    store = _make_store()
    uid = _activate_user(store)
    payload = SetupPayloadService(
        store,
        app_base_url="http://localhost:8000",
        mcp_auth_mode="hybrid",
        oauth_configured=True,
        oauth_link_configured=True,
    ).build_payload(uid)

    assert payload.oauth_enabled_for_mcp is True
    assert payload.oauth_link_enabled is True
    assert payload.api_keys_enabled_for_mcp is True
    assert payload.chatgpt_developer_mode.status == "ready"
    assert payload.vs_code.auth_method == "oauth_2_1"
    assert payload.cursor.auth_method == "oauth_2_1"
    assert payload.generic_http.auth_method == "caller_supplied_bearer_token"
    assert "${input:mcpDbAgentApiKey}" not in payload.vs_code.snippet
    assert "${env:MCP_DB_AGENT_API_KEY}" not in payload.cursor.snippet
    assert "<oauth-access-token>" in payload.generic_http.snippet


def test_oauth_only_mode_disables_api_key_payloads():
    store = _make_store()
    uid = _activate_user(store)
    payload = SetupPayloadService(
        store,
        app_base_url="http://localhost:8000",
        mcp_auth_mode="oauth_only",
        oauth_configured=True,
    ).build_payload(uid)

    assert payload.oauth_enabled_for_mcp is True
    assert payload.api_keys_enabled_for_mcp is False
    assert payload.vs_code.auth_method == "oauth_2_1"
    assert payload.cursor.auth_method == "oauth_2_1"
    assert payload.generic_http.auth_method == "caller_supplied_bearer_token"
    assert "api-key" not in payload.generic_http.snippet.lower()
