"""Tests for src/auth/user_store.py."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from src.auth.crypto import CredentialCipher
from src.auth.user_store import Base, UserStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    """In-memory SQLite engine with schema created fresh for each test."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def cipher():
    key = Fernet.generate_key().decode()
    return CredentialCipher([key])


@pytest.fixture
def store(engine, cipher):
    return UserStore(engine, cipher)


_PUBLIC_IP = "8.8.8.8"
_VALID_URL = f"postgresql://user:pass@{_PUBLIC_IP}/db"


def _make_user(store, url=_VALID_URL, provider="anthropic", ant_key=None, groq_key=None):
    with patch("socket.getaddrinfo") as mock_resolve:
        mock_resolve.return_value = [(2, 1, 0, "", (_PUBLIC_IP, 5432))]
        return store.create_user(url, provider, ant_key, groq_key)


# ---------------------------------------------------------------------------
# create_user
# ---------------------------------------------------------------------------


def test_create_user_returns_ids(store):
    user_id, raw_key = _make_user(store)
    assert isinstance(user_id, str) and len(user_id) == 36  # UUID4
    assert raw_key.startswith("mdbk_")
    assert len(raw_key) > 10


def test_create_user_key_not_stored_plaintext(store, engine):
    from sqlalchemy import text

    user_id, raw_key = _make_user(store)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT api_key_hash FROM users")).fetchall()
    assert len(rows) == 1
    stored_hash = rows[0][0]
    # The raw key must NOT appear in the hash column
    assert raw_key not in stored_hash
    # It must be a 64-char hex string (SHA-256)
    assert len(stored_hash) == 64


# ---------------------------------------------------------------------------
# get_user_by_api_key
# ---------------------------------------------------------------------------


def test_get_user_by_api_key_returns_config(store):
    user_id, raw_key = _make_user(store)
    config = store.get_user_by_api_key(raw_key)
    assert config is not None
    assert config.user_id == user_id
    assert config.database_url == _VALID_URL
    assert config.llm_provider == "anthropic"
    assert config.is_active is True


def test_wrong_key_returns_none(store):
    _make_user(store)
    assert store.get_user_by_api_key("mdbk_wrong_key") is None


def test_deactivated_user_returns_none(store):
    user_id, raw_key = _make_user(store)
    store.deactivate_user(user_id)
    assert store.get_user_by_api_key(raw_key) is None


# ---------------------------------------------------------------------------
# update_user
# ---------------------------------------------------------------------------


def test_update_user_partial_llm_provider(store):
    user_id, raw_key = _make_user(store, provider="anthropic")
    result = store.update_user(user_id, llm_provider="groq")
    assert result is True
    config = store.get_user_by_api_key(raw_key)
    assert config.llm_provider == "groq"


def test_update_user_returns_false_for_missing(store):
    assert store.update_user("nonexistent-id", llm_provider="groq") is False


def test_update_user_api_key_encrypted(store):
    user_id, raw_key = _make_user(store)
    store.update_user(user_id, anthropic_api_key="sk-ant-new-key")
    config = store.get_user_by_api_key(raw_key)
    assert config.anthropic_api_key == "sk-ant-new-key"


# ---------------------------------------------------------------------------
# rotate_api_key
# ---------------------------------------------------------------------------


def test_rotate_api_key_invalidates_old_key(store):
    user_id, old_key = _make_user(store)
    new_key = store.rotate_api_key(user_id)
    assert new_key.startswith("mdbk_")
    assert new_key != old_key
    # Old key must no longer work
    assert store.get_user_by_api_key(old_key) is None
    # New key must work
    config = store.get_user_by_api_key(new_key)
    assert config is not None
    assert config.user_id == user_id


def test_rotate_api_key_raises_for_missing(store):
    with pytest.raises(ValueError, match="not found"):
        store.rotate_api_key("nonexistent-id")


# ---------------------------------------------------------------------------
# deactivate_user
# ---------------------------------------------------------------------------


def test_deactivate_user_returns_true(store):
    user_id, _ = _make_user(store)
    assert store.deactivate_user(user_id) is True


def test_deactivate_user_returns_false_for_missing(store):
    assert store.deactivate_user("nonexistent-id") is False


# ---------------------------------------------------------------------------
# increment_daily_quota
# ---------------------------------------------------------------------------


def test_increment_daily_quota_counts_up(store):
    user_id, _ = _make_user(store)
    assert store.increment_daily_quota(user_id) == 1
    assert store.increment_daily_quota(user_id) == 2
    assert store.increment_daily_quota(user_id) == 3


def test_increment_daily_quota_resets_at_midnight(store):
    user_id, _ = _make_user(store)
    store.increment_daily_quota(user_id)
    store.increment_daily_quota(user_id)

    # Simulate the reset time having passed
    past_reset = datetime.now(UTC) - timedelta(hours=1)
    from sqlalchemy import text

    with store._engine.connect() as conn:
        conn.execute(
            text("UPDATE users SET daily_quota_reset_at = :t WHERE id = :id"),
            {"t": past_reset, "id": user_id},
        )
        conn.commit()

    count = store.increment_daily_quota(user_id)
    assert count == 1  # reset to 1, not 3


def test_increment_daily_quota_raises_for_missing(store):
    with pytest.raises(ValueError, match="not found"):
        store.increment_daily_quota("nonexistent-id")
