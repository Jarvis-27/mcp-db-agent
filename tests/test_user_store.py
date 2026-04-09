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

_MOCK_RESOLVE = [(2, 1, 0, "", (_PUBLIC_IP, 5432))]


def _make_user(store, url=_VALID_URL):
    import src.auth.url_guard as ug_module

    with patch("socket.getaddrinfo", return_value=_MOCK_RESOLVE), \
         patch.object(ug_module.settings, "environment", "development"):
        return store.create_user(url)


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


def test_create_user_sanitizes_dangerous_params(store):
    """Dangerous query params must not survive persistence."""
    import src.auth.url_guard as ug_module

    dirty_url = f"postgresql://user:pass@{_PUBLIC_IP}/db?passfile=/etc/passwd&sslmode=require"
    with patch("socket.getaddrinfo", return_value=_MOCK_RESOLVE), \
         patch.object(ug_module.settings, "environment", "development"):
        user_id, raw_key = store.create_user(dirty_url)
    config = store.get_user_by_api_key(raw_key)
    assert config is not None
    assert "passfile" not in config.database_url
    assert "sslmode=require" in config.database_url  # safe param survives


# ---------------------------------------------------------------------------
# get_user_by_api_key
# ---------------------------------------------------------------------------


def test_get_user_by_api_key_returns_config(store):
    user_id, raw_key = _make_user(store)
    config = store.get_user_by_api_key(raw_key)
    assert config is not None
    assert config.user_id == user_id
    assert config.database_url == _VALID_URL
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


def test_update_user_database_url(store):
    import src.auth.url_guard as ug_module

    user_id, raw_key = _make_user(store)
    new_url = f"postgresql://newuser:newpass@{_PUBLIC_IP}/newdb"
    with patch("socket.getaddrinfo", return_value=_MOCK_RESOLVE), \
         patch.object(ug_module.settings, "environment", "development"):
        result = store.update_user(user_id, database_url=new_url)
    assert result is True
    config = store.get_user_by_api_key(raw_key)
    assert config is not None
    assert config.database_url == new_url


def test_update_user_sanitizes_dangerous_params(store):
    """Dangerous query params must not survive a database URL update."""
    import src.auth.url_guard as ug_module

    user_id, raw_key = _make_user(store)
    dirty_url = f"postgresql://user:pass@{_PUBLIC_IP}/db?sslkey=/etc/ssl/key.pem&sslmode=require"
    with patch("socket.getaddrinfo", return_value=_MOCK_RESOLVE), \
         patch.object(ug_module.settings, "environment", "development"):
        store.update_user(user_id, database_url=dirty_url)
    config = store.get_user_by_api_key(raw_key)
    assert config is not None
    assert "sslkey" not in config.database_url
    assert "sslmode=require" in config.database_url  # safe param survives


def test_update_user_returns_false_for_missing(store):
    assert store.update_user("nonexistent-id") is False


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


def test_increment_daily_quota_concurrent_no_lost_updates(tmp_path, cipher):
    """Concurrent increments must not lose updates (no read/modify/write race).

    Uses a file-backed SQLite database (not StaticPool) so that multiple
    threads each get their own connection from the pool.  This exercises the
    actual serialization guarantee of the atomic UPDATE … RETURNING statement.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    db_path = tmp_path / "concurrent_test.db"
    eng = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    file_store = UserStore(eng, cipher)

    try:
        user_id, _ = _make_user(file_store)
        n = 20

        with ThreadPoolExecutor(max_workers=n) as pool:
            futures = [pool.submit(file_store.increment_daily_quota, user_id) for _ in range(n)]
            results = sorted(f.result() for f in as_completed(futures))

        # Every increment must return a unique, consecutive value 1..n.
        # If any two increments returned the same value an update was lost.
        assert results == list(range(1, n + 1))
    finally:
        eng.dispose()
