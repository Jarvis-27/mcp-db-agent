"""Tests for the user-centric UserStore."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.auth.crypto import CredentialCipher
from src.auth.onboarding import ACCOUNT_ACTIVE, ACCOUNT_CLOSED, ACCOUNT_SUSPENDED, SETUP_COMPLETE
from src.auth.user_store import Base, DailyQuotaSnapshot, UserStore


@pytest.fixture
def engine():
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


def _make_active_user(store, email="owner@example.com"):
    """Create a fully activated user via the self-serve path."""
    user_id = store.create_user(email=email)
    store.set_email_verified(user_id)
    store.transition_user_state(user_id, "pending_db_connection")
    store.upsert_user_database(user_id, store._cipher.encrypt(_VALID_URL))
    store.activate_user(user_id)  # sets setup_complete + active + free plan
    raw_key, api_key = store.create_api_key(
        user_id=user_id,
        name="default",
        scopes=["mcp_read"],
    )
    return user_id, raw_key, api_key.id


def _make_active_user_without_keys(store, email="owner-no-key@example.com"):
    user_id = store.create_user(email=email)
    store.set_email_verified(user_id)
    store.transition_user_state(user_id, "pending_db_connection")
    store.upsert_user_database(user_id, store._cipher.encrypt(_VALID_URL))
    store.activate_user(user_id)
    return user_id


def test_create_user_returns_pending_id(store):
    user_id = store.create_user(email="pending@example.com")
    assert isinstance(user_id, str)
    assert store.get_user_onboarding_status(user_id) == "pending_email_verification"
    config = store.get_user_by_id(user_id)
    assert config is not None
    assert config.is_active is False


def test_create_user_new_has_correct_defaults(store):
    user_id = store.create_user("new@example.com")
    user = store.get_user_row(user_id)
    assert user is not None
    assert str(user.account_status) == ACCOUNT_ACTIVE
    assert str(user.billing_status) == "free"
    assert str(user.plan_code) == "free"


def test_issue_user_session_returns_authenticated_context(store):
    user_id = store.create_user("owner@example.com")
    raw = store.issue_user_session(user_id, ttl_hours=24)
    ctx = store.get_user_by_session(raw)
    assert ctx is not None
    assert ctx.user_id == user_id


def test_get_user_by_api_key_returns_user_context(store):
    user_id, raw_key, api_key_id = _make_active_user(store)
    config = store.get_user_by_api_key(raw_key)
    assert config is not None
    assert config.user_id == user_id
    assert config.api_key_id == api_key_id
    assert config.database_url == _VALID_URL
    assert config.is_active is True
    assert "mcp_read" in config.scopes
    assert config.account_status == ACCOUNT_ACTIVE
    assert config.plan_code == "free"


def test_revoked_key_returns_none(store):
    user_id, raw_key, api_key_id = _make_active_user(store)
    assert store.revoke_api_key(user_id, str(api_key_id)) is True
    assert store.get_user_by_api_key(raw_key) is None


def test_suspended_user_key_returns_none(store):
    user_id, raw_key, _api_key_id = _make_active_user(store)
    store.set_account_status(user_id, ACCOUNT_SUSPENDED)
    assert store.get_user_by_api_key(raw_key) is None


def test_activate_user_sets_correct_state(store):
    user_id = store.create_user("a@example.com")
    store.set_email_verified(user_id)
    store.transition_user_state(user_id, "pending_db_connection")
    store.upsert_user_database(user_id, store._cipher.encrypt(_VALID_URL))
    store.activate_user(user_id)

    user = store.get_user_row(user_id)
    assert user is not None
    assert str(user.onboarding_status) == SETUP_COMPLETE
    assert str(user.account_status) == ACCOUNT_ACTIVE
    assert str(user.billing_status) == "free"
    assert str(user.plan_code) == "free"


def test_set_account_status_suspends_user(store):
    user_id, _, _ = _make_active_user(store)
    ok = store.set_account_status(user_id, ACCOUNT_SUSPENDED)
    assert ok is True
    assert store.get_user_account_status(user_id) == ACCOUNT_SUSPENDED


def test_set_account_status_closed_is_terminal(store):
    user_id, _, _ = _make_active_user(store)
    store.set_account_status(user_id, ACCOUNT_CLOSED)
    ok = store.set_account_status(user_id, ACCOUNT_ACTIVE)
    assert ok is False
    assert store.get_user_account_status(user_id) == ACCOUNT_CLOSED


def test_rotate_api_key_invalidates_old_key(store):
    user_id, old_key, api_key_id = _make_active_user(store)
    new_key = store.rotate_api_key(user_id, str(api_key_id))
    assert new_key.startswith("mdbk_")
    assert store.get_user_by_api_key(old_key) is None
    config = store.get_user_by_api_key(new_key)
    assert config is not None
    assert config.user_id == user_id
    assert store.count_active_api_keys(user_id) == 1


def test_count_active_api_keys(store):
    user_id, _, key_id = _make_active_user(store)
    assert store.count_active_api_keys(user_id) == 1
    store.revoke_api_key(user_id, str(key_id))
    assert store.count_active_api_keys(user_id) == 0


def test_create_api_key_respects_plan_limit(store):
    """Free plan allows only 1 API key."""
    from src.auth.user_store import StateTransitionError

    user_id, _, _ = _make_active_user(store)
    # Already has 1 key from _make_active_user; free plan limit is 1.
    with pytest.raises(StateTransitionError, match="API key limit"):
        store.create_api_key(
            user_id=user_id,
            name="second-key",
            scopes=["mcp_read"],
        )


def test_consume_daily_query_quota_returns_plan_snapshot(store):
    user_id, _, _ = _make_active_user(store)
    snapshot = store.consume_daily_query_quota(user_id)
    assert isinstance(snapshot, DailyQuotaSnapshot)
    assert snapshot.user_id == user_id
    assert snapshot.plan_code == "free"
    assert snapshot.daily_count == 1
    assert snapshot.daily_quota_reset_at.tzinfo is not None


def test_consume_daily_quota_counts_up(store):
    user_id, _, _ = _make_active_user(store)
    assert store.consume_daily_query_quota(user_id).daily_count == 1
    assert store.consume_daily_query_quota(user_id).daily_count == 2
    assert store.consume_daily_query_quota(user_id).daily_count == 3


def test_consume_daily_quota_resets_at_midnight(store):
    user_id, _, _ = _make_active_user(store)
    store.consume_daily_query_quota(user_id)
    store.consume_daily_query_quota(user_id)

    past_reset = datetime.now(UTC) - timedelta(hours=1)
    with store._engine.connect() as conn:
        conn.execute(
            text("UPDATE users SET daily_quota_reset_at = :t WHERE id = :id"),
            {"t": past_reset, "id": user_id},
        )
        conn.commit()

    assert store.consume_daily_query_quota(user_id).daily_count == 1


def test_consume_daily_quota_concurrent_no_lost_updates(tmp_path, cipher):
    db_path = tmp_path / "concurrent_test.db"
    eng = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    file_store = UserStore(eng, cipher)

    try:
        user_id, _, _ = _make_active_user(file_store)
        n = 20
        with ThreadPoolExecutor(max_workers=n) as pool:
            futures = [pool.submit(file_store.consume_daily_query_quota, user_id) for _ in range(n)]
            results = sorted(f.result().daily_count for f in as_completed(futures))
        assert results == list(range(1, n + 1))
    finally:
        eng.dispose()


def test_upsert_user_database_replaces_existing(store):
    user_id = _make_active_user_without_keys(store)
    first_url = f"postgresql://u:p@{_PUBLIC_IP}/db1"
    second_url = f"postgresql://u:p@{_PUBLIC_IP}/db2"
    store.upsert_user_database(user_id, store._cipher.encrypt(first_url))
    store.upsert_user_database(user_id, store._cipher.encrypt(second_url))

    config = store.get_user_by_id(user_id)
    assert config is not None
    assert config.database_url == second_url


def test_get_active_database_returns_info(store):
    user_id = _make_active_user_without_keys(store)
    db_info = store.get_active_database(user_id)
    assert db_info is not None
    assert db_info.name == "primary"
    assert db_info.validation_status == "validated"


def test_get_active_database_before_submit_returns_none(store):
    user_id = store.create_user("nokey@example.com")
    assert store.get_active_database(user_id) is None


def test_user_can_issue_api_keys_requires_db(store):
    user_id = _make_active_user_without_keys(store)
    assert store.user_can_issue_api_keys(user_id) is True


def test_user_cannot_issue_api_keys_without_db(store):
    user_id = store.create_user("nodb@example.com")
    store.set_email_verified(user_id)
    store.transition_user_state(user_id, "pending_db_connection")
    # Don't activate or add DB
    assert store.user_can_issue_api_keys(user_id) is False


def test_get_user_by_email_returns_session_context(store):
    user_id = store.create_user("email@example.com")
    ctx = store.get_user_by_email("email@example.com")
    assert ctx is not None
    assert ctx.user_id == user_id


def test_get_user_by_email_returns_none_for_unknown(store):
    assert store.get_user_by_email("ghost@example.com") is None


def test_create_user_normalises_email_to_lowercase(store):
    user_id = store.create_user("Mixed@Case.COM")
    row = store.get_user_row(user_id)
    assert row is not None
    assert str(row.email) == "mixed@case.com"


def test_get_user_by_email_is_case_insensitive(store):
    user_id = store.create_user("Upper@Example.COM")
    ctx = store.get_user_by_email("upper@example.com")
    assert ctx is not None
    assert ctx.user_id == user_id


def test_email_exists_returns_true_for_active_user(store):
    store.create_user("active@example.com")
    assert store.email_exists("active@example.com") is True


def test_email_exists_is_case_insensitive(store):
    store.create_user("owns@example.com")
    assert store.email_exists("OWNS@EXAMPLE.COM") is True


def test_email_exists_returns_true_for_closed_account(store):
    """email_exists must return True even after the account is closed."""
    user_id = store.create_user("closed@example.com")
    store.set_account_status(user_id, ACCOUNT_CLOSED)
    assert store.email_exists("closed@example.com") is True


def test_email_exists_returns_false_for_unknown(store):
    assert store.email_exists("nobody@example.com") is False


def test_revoke_user_session(store):
    user_id = store.create_user("sess@example.com")
    raw = store.issue_user_session(user_id, ttl_hours=24)
    assert store.get_user_by_session(raw) is not None
    store.revoke_user_session(raw)
    assert store.get_user_by_session(raw) is None


# ---------------------------------------------------------------------------
# Timezone-aware daily quota behaviour
# ---------------------------------------------------------------------------


def test_create_user_default_timezone_is_utc(store):
    user_id = store.create_user("default-tz@example.com")
    user = store.get_user_row(user_id)
    assert user is not None
    assert str(user.timezone) == "UTC"


def test_create_user_stores_provided_timezone(store):
    user_id = store.create_user("ist@example.com", timezone="Asia/Kolkata")
    user = store.get_user_row(user_id)
    assert user is not None
    assert str(user.timezone) == "Asia/Kolkata"


def test_create_user_invalid_timezone_falls_back_to_utc(store):
    user_id = store.create_user("bogus-tz@example.com", timezone="Not/A_Real_Zone")
    user = store.get_user_row(user_id)
    assert user is not None
    assert str(user.timezone) == "UTC"


def test_create_user_initial_reset_at_aligned_to_local_midnight(store):
    from zoneinfo import ZoneInfo

    user_id = store.create_user("ist-init@example.com", timezone="Asia/Kolkata")
    user = store.get_user_row(user_id)
    assert user is not None
    reset_at = user.daily_quota_reset_at
    if reset_at.tzinfo is None:
        reset_at = reset_at.replace(tzinfo=UTC)
    local = reset_at.astimezone(ZoneInfo("Asia/Kolkata"))
    assert (local.hour, local.minute, local.second) == (0, 0, 0)


def test_get_effective_quota_snapshot_returns_stored_when_future_reset(store):
    user_id, _, _ = _make_active_user(store)
    store.consume_daily_query_quota(user_id)
    store.consume_daily_query_quota(user_id)

    snap = store.get_effective_quota_snapshot(user_id)
    assert snap is not None
    assert snap.daily_count == 2
    assert snap.daily_quota_reset_at > datetime.now(UTC)


def test_get_effective_quota_snapshot_virtualizes_zero_when_past_reset(store):
    user_id, _, _ = _make_active_user(store)
    store.consume_daily_query_quota(user_id)
    store.consume_daily_query_quota(user_id)

    past_reset = datetime.now(UTC) - timedelta(hours=1)
    with store._engine.connect() as conn:
        conn.execute(
            text("UPDATE users SET daily_quota_reset_at = :t WHERE id = :id"),
            {"t": past_reset, "id": user_id},
        )
        conn.commit()

    snap = store.get_effective_quota_snapshot(user_id)
    assert snap is not None
    assert snap.daily_count == 0
    assert snap.daily_quota_reset_at > datetime.now(UTC)


def test_get_effective_quota_snapshot_does_not_persist(store):
    user_id, _, _ = _make_active_user(store)
    store.consume_daily_query_quota(user_id)
    store.consume_daily_query_quota(user_id)

    past_reset = datetime.now(UTC) - timedelta(hours=1)
    with store._engine.connect() as conn:
        conn.execute(
            text("UPDATE users SET daily_quota_reset_at = :t WHERE id = :id"),
            {"t": past_reset, "id": user_id},
        )
        conn.commit()

    # Calling the read helper must NOT mutate the row.
    store.get_effective_quota_snapshot(user_id)
    store.get_effective_quota_snapshot(user_id)

    user = store.get_user_row(user_id)
    assert user is not None
    assert int(user.daily_query_count) == 2  # unchanged
    stored_reset = user.daily_quota_reset_at
    if stored_reset.tzinfo is None:
        stored_reset = stored_reset.replace(tzinfo=UTC)
    assert stored_reset < datetime.now(UTC)  # still backdated


def test_get_effective_quota_snapshot_unknown_user_returns_none(store):
    assert store.get_effective_quota_snapshot("00000000-0000-0000-0000-000000000000") is None


def test_update_timezone_recomputes_reset_at(store):
    from zoneinfo import ZoneInfo

    user_id = store.create_user("tz-update@example.com", timezone="UTC")
    assert store.update_timezone(user_id, "Asia/Kolkata") is True

    user = store.get_user_row(user_id)
    assert user is not None
    assert str(user.timezone) == "Asia/Kolkata"
    reset_at = user.daily_quota_reset_at
    if reset_at.tzinfo is None:
        reset_at = reset_at.replace(tzinfo=UTC)
    local = reset_at.astimezone(ZoneInfo("Asia/Kolkata"))
    assert (local.hour, local.minute) == (0, 0)


def test_update_timezone_invalid_falls_back_to_utc(store):
    user_id = store.create_user("bogus-update@example.com", timezone="Asia/Kolkata")
    assert store.update_timezone(user_id, "Not/A_Real_Zone") is True
    user = store.get_user_row(user_id)
    assert user is not None
    assert str(user.timezone) == "UTC"


def test_update_timezone_unknown_user_returns_false(store):
    assert store.update_timezone("00000000-0000-0000-0000-000000000000", "UTC") is False


def test_consume_quota_uses_user_timezone(store):
    from zoneinfo import ZoneInfo

    user_id = store.create_user("consumer-ist@example.com", timezone="Asia/Kolkata")
    snap = store.consume_daily_query_quota(user_id)
    assert snap.timezone == "Asia/Kolkata"
    reset_at = snap.daily_quota_reset_at
    local = reset_at.astimezone(ZoneInfo("Asia/Kolkata"))
    assert (local.hour, local.minute, local.second) == (0, 0, 0)


def test_consume_quota_resets_at_local_midnight(store):
    user_id = store.create_user("reset-ist@example.com", timezone="Asia/Kolkata")
    # First consume sets count=1 and computes initial reset_at.
    store.consume_daily_query_quota(user_id)
    store.consume_daily_query_quota(user_id)

    # Force reset window into the past.
    past_reset = datetime.now(UTC) - timedelta(minutes=5)
    with store._engine.connect() as conn:
        conn.execute(
            text("UPDATE users SET daily_quota_reset_at = :t WHERE id = :id"),
            {"t": past_reset, "id": user_id},
        )
        conn.commit()

    snap = store.consume_daily_query_quota(user_id)
    assert snap.daily_count == 1  # reset to 1 on first consume after boundary
    assert snap.daily_quota_reset_at > datetime.now(UTC)
