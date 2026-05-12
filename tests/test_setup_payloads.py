"""Unit tests for setup payload generation."""

from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.auth.crypto import CredentialCipher
from src.auth.user_store import Base, UserStore
from src.setup.service import SetupPayloadInputError, SetupPayloadService

_VALID_URL = "postgresql://user:pass@8.8.8.8/appdb"


def _make_store() -> UserStore:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    cipher = CredentialCipher([Fernet.generate_key().decode()])
    return UserStore(engine, cipher)


def _activate_user(store: UserStore, *, email: str = "owner@example.com") -> str:
    user_id = store.create_user(email=email)
    store.set_email_verified(user_id)
    store.transition_user_state(user_id, "pending_db_connection")
    store.upsert_user_database(user_id, store._cipher.encrypt(_VALID_URL))
    store.activate_user(user_id)
    return user_id


def test_service_uses_placeholder_when_raw_key_not_supplied():
    store = _make_store()
    user_id = _activate_user(store)
    raw_key, api_key = store.create_api_key(
        user_id=user_id,
        name="default",
        scopes=["mcp_read"],
    )
    service = SetupPayloadService(store, app_base_url="http://localhost:8000")

    payload = service.build_payload(user_id)

    assert payload.api_key_state.active_key_count == 1
    assert payload.api_key_state.selected_api_key_id == str(api_key.id)
    assert payload.api_key_state.raw_key_included is False
    assert payload.api_key_state.requires_manual_key_entry is True
    assert raw_key not in payload.vs_code.snippet
    assert "${input:mcpDbAgentApiKey}" in payload.vs_code.snippet
    assert "${env:MCP_DB_AGENT_API_KEY}" in payload.cursor.snippet
    assert "<paste-api-key-here>" in payload.generic_http.snippet


def test_service_embeds_raw_key_only_when_explicitly_provided():
    store = _make_store()
    user_id = _activate_user(store)
    raw_key, api_key = store.create_api_key(
        user_id=user_id,
        name="default",
        scopes=["mcp_read"],
    )
    service = SetupPayloadService(store, app_base_url="http://localhost:8000")

    payload = service.build_payload(user_id, raw_api_key=raw_key)

    assert payload.api_key_state.selected_api_key_id == str(api_key.id)
    assert payload.api_key_state.raw_key_included is True
    assert payload.api_key_state.requires_manual_key_entry is False
    assert raw_key in payload.vs_code.snippet
    assert raw_key in payload.cursor.snippet
    assert raw_key in payload.generic_http.snippet


def test_service_rejects_revoked_raw_key():
    store = _make_store()
    user_id = _activate_user(store)
    raw_key, api_key = store.create_api_key(
        user_id=user_id,
        name="default",
        scopes=["mcp_read"],
    )
    assert store.revoke_api_key(user_id, str(api_key.id)) is True
    service = SetupPayloadService(store, app_base_url="http://localhost:8000")

    try:
        service.build_payload(user_id, raw_api_key=raw_key)
    except SetupPayloadInputError as exc:
        assert "does not match an active api key" in str(exc).lower()
    else:  # pragma: no cover - explicit failure path
        raise AssertionError("expected SetupPayloadInputError")


def test_service_returns_live_quota_summary_for_pro_plan():
    store = _make_store()
    user_id = _activate_user(store)
    next_reset = datetime.now(UTC) + timedelta(hours=3)
    with store._engine.connect() as conn:
        conn.execute(
            text(
                "UPDATE users SET plan_code = 'pro', daily_query_count = 123,"
                " daily_quota_reset_at = :reset WHERE id = :id"
            ),
            {"reset": next_reset, "id": user_id},
        )
        conn.commit()

    service = SetupPayloadService(store, app_base_url="http://localhost:8000")
    payload = service.build_payload(user_id)

    assert payload.plan_code == "pro"
    assert payload.quota_summary.daily_limit == 500
    assert payload.quota_summary.daily_used == 123
    assert payload.quota_summary.daily_remaining == 377
    assert payload.quota_summary.reset_at == next_reset


def test_chatgpt_payload_is_marked_unavailable_until_oauth():
    store = _make_store()
    user_id = _activate_user(store)
    service = SetupPayloadService(store, app_base_url="http://localhost:8000")

    payload = service.build_payload(user_id)

    assert payload.chatgpt_developer_mode.status == "unsupported_until_oauth"
    assert payload.chatgpt_developer_mode.auth_method == "oauth_2_1_required"
    assert payload.chatgpt_developer_mode.snippet == ""


def test_setup_payload_virtualizes_quota_after_local_midnight():
    store = _make_store()
    user_id = _activate_user(store)
    # Simulate yesterday's usage that has not yet been reset by a consume call.
    past_reset = datetime.now(UTC) - timedelta(hours=2)
    with store._engine.connect() as conn:
        conn.execute(
            text(
                "UPDATE users SET timezone = :tz, daily_query_count = 7,"
                " daily_quota_reset_at = :reset WHERE id = :id"
            ),
            {"tz": "Asia/Kolkata", "reset": past_reset, "id": user_id},
        )
        conn.commit()

    service = SetupPayloadService(store, app_base_url="http://localhost:8000")
    payload = service.build_payload(user_id)

    assert payload.quota_summary.daily_used == 0
    assert payload.quota_summary.daily_remaining == payload.quota_summary.daily_limit
    assert payload.quota_summary.reset_at > datetime.now(UTC)
    assert payload.quota_summary.warning_level in (None, "none")

    # Read-side virtualization must not have mutated the stored row.
    with store._engine.connect() as conn:
        row = conn.execute(
            text("SELECT daily_query_count FROM users WHERE id = :id"),
            {"id": user_id},
        ).fetchone()
    assert row is not None
    assert int(row[0]) == 7
