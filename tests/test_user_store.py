"""Tests for the tenant-backed UserStore."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.auth.crypto import CredentialCipher
from src.auth.onboarding import ACCOUNT_ACTIVE, ACCOUNT_CLOSED, ACCOUNT_SUSPENDED, SETUP_COMPLETE
from src.auth.user_store import Base, UserStore


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


def _make_active_tenant(store, email="owner@example.com"):
    """Create a fully activated tenant via the self-serve path (no pending_review)."""
    tenant_id, membership_id = store.create_tenant_with_owner(email=email)
    store.set_email_verified(membership_id)
    store.transition_tenant_state(tenant_id, "pending_db_connection")
    store.upsert_active_database(tenant_id, store._cipher.encrypt(_VALID_URL))
    store.activate_tenant(tenant_id)  # sets setup_complete + active + free plan
    raw_key, api_key = store.create_api_key(
        tenant_id=tenant_id,
        name="default",
        scopes=["mcp_read"],
        created_by_membership_id=membership_id,
    )
    return tenant_id, membership_id, raw_key, api_key.id


def test_create_user_returns_pending_tenant_id(store):
    tenant_id = store.create_user(email="pending@example.com")
    assert isinstance(tenant_id, str)
    assert store.get_onboarding_status(tenant_id) == "pending_email_verification"
    config = store.get_user_by_id(tenant_id)
    assert config is not None
    assert config.is_active is False


def test_create_tenant_with_owner_returns_membership(store):
    tenant_id, membership_id = store.create_tenant_with_owner("owner@example.com", "Acme")
    owner = store.get_owner_membership_by_id(membership_id)
    assert owner is not None
    assert owner.tenant_id == tenant_id
    assert owner.email == "owner@example.com"
    assert owner.onboarding_status == "pending_email_verification"


def test_new_tenant_has_correct_defaults(store):
    tenant_id, _ = store.create_tenant_with_owner("new@example.com")
    tenant = store.get_tenant(tenant_id)
    assert tenant is not None
    assert str(tenant.account_status) == ACCOUNT_ACTIVE
    assert str(tenant.billing_status) == "free"
    assert str(tenant.plan_code) == "free"


def test_issue_owner_session_returns_authenticated_owner(store):
    tenant_id, membership_id = store.create_tenant_with_owner("owner@example.com")
    raw = store.issue_owner_session(membership_id, ttl_hours=24)
    owner = store.get_owner_by_session(raw)
    assert owner is not None
    assert owner.tenant_id == tenant_id
    assert owner.membership_id == membership_id


def test_get_user_by_api_key_returns_tenant_context(store):
    tenant_id, _membership_id, raw_key, api_key_id = _make_active_tenant(store)
    config = store.get_user_by_api_key(raw_key)
    assert config is not None
    assert config.user_id == tenant_id
    assert config.api_key_id == api_key_id
    assert config.database_url == _VALID_URL
    assert config.is_active is True
    assert "mcp_read" in config.scopes
    assert config.account_status == ACCOUNT_ACTIVE
    assert config.plan_code == "free"


def test_revoked_key_returns_none(store):
    tenant_id, _membership_id, raw_key, api_key_id = _make_active_tenant(store)
    assert store.revoke_api_key(tenant_id, str(api_key_id)) is True
    assert store.get_user_by_api_key(raw_key) is None


def test_suspended_tenant_key_returns_none(store):
    tenant_id, _membership_id, raw_key, _api_key_id = _make_active_tenant(store)
    store.set_account_status(tenant_id, ACCOUNT_SUSPENDED)
    assert store.get_user_by_api_key(raw_key) is None


def test_activate_tenant_sets_correct_state(store):
    tenant_id, membership_id = store.create_tenant_with_owner("a@example.com")
    store.set_email_verified(membership_id)
    store.transition_tenant_state(tenant_id, "pending_db_connection")
    store.upsert_active_database(tenant_id, store._cipher.encrypt(_VALID_URL))
    store.activate_tenant(tenant_id)

    tenant = store.get_tenant(tenant_id)
    assert tenant is not None
    assert str(tenant.status) == SETUP_COMPLETE
    assert str(tenant.account_status) == ACCOUNT_ACTIVE
    assert str(tenant.billing_status) == "free"
    assert str(tenant.plan_code) == "free"


def test_set_account_status_suspends_tenant(store):
    tenant_id, _, _, _ = _make_active_tenant(store)
    ok = store.set_account_status(tenant_id, ACCOUNT_SUSPENDED)
    assert ok is True
    assert store.get_tenant_account_status(tenant_id) == ACCOUNT_SUSPENDED


def test_set_account_status_closed_is_terminal(store):
    tenant_id, _, _, _ = _make_active_tenant(store)
    store.set_account_status(tenant_id, ACCOUNT_CLOSED)
    # Cannot change from closed
    ok = store.set_account_status(tenant_id, ACCOUNT_ACTIVE)
    assert ok is False
    assert store.get_tenant_account_status(tenant_id) == ACCOUNT_CLOSED


def test_update_user_database_url_updates_active_database(store):
    import src.auth.url_guard as ug_module

    tenant_id, _membership_id, raw_key, _api_key_id = _make_active_tenant(store)
    new_url = f"postgresql://newuser:newpass@{_PUBLIC_IP}/newdb"
    with (
        patch("socket.getaddrinfo", return_value=[(2, 1, 0, "", (_PUBLIC_IP, 5432))]),
        patch.object(ug_module.settings, "environment", "development"),
    ):
        assert store.update_user(tenant_id, database_url=new_url) is True
    config = store.get_user_by_api_key(raw_key)
    assert config is not None
    assert config.database_url == new_url


def test_rotate_api_key_invalidates_old_key(store):
    tenant_id, _membership_id, old_key, api_key_id = _make_active_tenant(store)
    new_key = store.rotate_api_key(tenant_id, str(api_key_id))
    assert new_key.startswith("mdbk_")
    assert store.get_user_by_api_key(old_key) is None
    config = store.get_user_by_api_key(new_key)
    assert config is not None
    assert config.user_id == tenant_id


def test_count_active_api_keys(store):
    tenant_id, _, _, key_id = _make_active_tenant(store)
    assert store.count_active_api_keys(tenant_id) == 1
    store.revoke_api_key(tenant_id, str(key_id))
    assert store.count_active_api_keys(tenant_id) == 0


def test_create_api_key_respects_plan_limit(store):
    """Free plan allows only 1 API key."""
    from src.auth.user_store import StateTransitionError

    tenant_id, _, _, _ = _make_active_tenant(store)
    # Already has 1 key from _make_active_tenant; free plan limit is 1.
    with pytest.raises(StateTransitionError, match="API key limit"):
        store.create_api_key(
            tenant_id=tenant_id,
            name="second-key",
            scopes=["mcp_read"],
            created_by_membership_id=None,
        )


def test_list_tenants_by_account_status(store):
    tid1, _, _, _ = _make_active_tenant(store, email="a@example.com")
    tid2, _, _, _ = _make_active_tenant(store, email="b@example.com")
    store.set_account_status(tid1, ACCOUNT_SUSPENDED)

    suspended = [t.id for t, _ in store.list_tenants_by_account_status(ACCOUNT_SUSPENDED)]
    assert tid1 in suspended
    assert tid2 not in suspended


def test_increment_daily_quota_counts_up(store):
    tenant_id, _membership_id, _raw_key, _api_key_id = _make_active_tenant(store)
    assert store.increment_daily_quota(tenant_id) == 1
    assert store.increment_daily_quota(tenant_id) == 2
    assert store.increment_daily_quota(tenant_id) == 3


def test_increment_daily_quota_resets_at_midnight(store):
    tenant_id, _membership_id, _raw_key, _api_key_id = _make_active_tenant(store)
    store.increment_daily_quota(tenant_id)
    store.increment_daily_quota(tenant_id)

    past_reset = datetime.now(UTC) - timedelta(hours=1)
    with store._engine.connect() as conn:
        conn.execute(
            text("UPDATE tenants SET daily_quota_reset_at = :t WHERE id = :id"),
            {"t": past_reset, "id": tenant_id},
        )
        conn.commit()

    assert store.increment_daily_quota(tenant_id) == 1


def test_increment_daily_quota_concurrent_no_lost_updates(tmp_path, cipher):
    from concurrent.futures import ThreadPoolExecutor, as_completed

    db_path = tmp_path / "concurrent_test.db"
    eng = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    file_store = UserStore(eng, cipher)

    try:
        tenant_id, _membership_id, _raw_key, _api_key_id = _make_active_tenant(file_store)
        n = 20
        with ThreadPoolExecutor(max_workers=n) as pool:
            futures = [pool.submit(file_store.increment_daily_quota, tenant_id) for _ in range(n)]
            results = sorted(f.result() for f in as_completed(futures))
        assert results == list(range(1, n + 1))
    finally:
        eng.dispose()
