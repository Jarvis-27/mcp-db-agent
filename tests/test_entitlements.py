"""Tests for the entitlements module — plan definitions and service checks."""

import pytest

from src.entitlements.plans import FREE_PLAN, PRO_PLAN, Plan, get_plan
from src.entitlements.service import EntitlementService


# ---------------------------------------------------------------------------
# Plan definitions
# ---------------------------------------------------------------------------


def test_free_plan_has_correct_quotas():
    assert FREE_PLAN.code == "free"
    assert FREE_PLAN.ask_database_per_day == 25
    assert FREE_PLAN.max_api_keys == 1
    assert FREE_PLAN.max_active_databases == 1


def test_pro_plan_has_correct_quotas():
    assert PRO_PLAN.code == "pro"
    assert PRO_PLAN.ask_database_per_day == 500
    assert PRO_PLAN.max_api_keys == 5
    assert PRO_PLAN.max_active_databases == 1


def test_get_plan_returns_correct_plan():
    assert get_plan("free") is FREE_PLAN
    assert get_plan("pro") is PRO_PLAN


def test_get_plan_unknown_code_defaults_to_free():
    result = get_plan("unknown_tier")
    assert result is FREE_PLAN


def test_plan_is_immutable():
    with pytest.raises((AttributeError, TypeError)):
        FREE_PLAN.ask_database_per_day = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# EntitlementService — query quota
# ---------------------------------------------------------------------------


@pytest.fixture
def svc():
    return EntitlementService()


def test_query_quota_below_limit_is_allowed(svc):
    result = svc.check_query_quota("free", current_daily_count=0)
    assert result.allowed is True
    assert result.limit == 25
    assert result.current == 0
    assert result.plan_code == "free"
    assert result.reason is None


def test_query_quota_at_limit_is_denied(svc):
    result = svc.check_query_quota("free", current_daily_count=25)
    assert result.allowed is False
    assert result.reason == "daily_quota_exceeded"


def test_query_quota_below_limit_for_free(svc):
    result = svc.check_query_quota("free", current_daily_count=24)
    assert result.allowed is True


def test_query_quota_pro_plan_higher_limit(svc):
    result = svc.check_query_quota("pro", current_daily_count=499)
    assert result.allowed is True
    result_over = svc.check_query_quota("pro", current_daily_count=500)
    assert result_over.allowed is False


# ---------------------------------------------------------------------------
# EntitlementService — API key quota
# ---------------------------------------------------------------------------


def test_api_key_quota_free_allows_first_key(svc):
    result = svc.check_api_key_quota("free", current_key_count=0)
    assert result.allowed is True
    assert result.limit == 1
    assert result.plan_code == "free"


def test_api_key_quota_free_denies_second_key(svc):
    result = svc.check_api_key_quota("free", current_key_count=1)
    assert result.allowed is False
    assert result.reason == "api_key_limit_reached"


def test_api_key_quota_pro_allows_up_to_five(svc):
    for i in range(5):
        assert svc.check_api_key_quota("pro", current_key_count=i).allowed is True
    assert svc.check_api_key_quota("pro", current_key_count=5).allowed is False


# ---------------------------------------------------------------------------
# EntitlementService — database quota
# ---------------------------------------------------------------------------


def test_database_quota_free_allows_first(svc):
    result = svc.check_database_quota("free", current_db_count=0)
    assert result.allowed is True
    assert result.limit == 1
    assert result.plan_code == "free"


def test_database_quota_free_denies_second(svc):
    result = svc.check_database_quota("free", current_db_count=1)
    assert result.allowed is False
    assert result.reason == "database_limit_reached"


def test_database_quota_pro_denies_second(svc):
    result = svc.check_database_quota("pro", current_db_count=1)
    assert result.allowed is False
    assert result.reason == "database_limit_reached"


# ---------------------------------------------------------------------------
# EntitlementService — quota warning level
# ---------------------------------------------------------------------------


def test_no_warning_at_low_usage(svc):
    assert svc.quota_warning_level("free", 0) is None
    assert svc.quota_warning_level("free", 12) is None  # 48% < 50%


def test_medium_warning_at_50_percent(svc):
    assert svc.quota_warning_level("free", 13) == "medium"  # 52%


def test_high_warning_at_80_percent(svc):
    assert svc.quota_warning_level("free", 20) == "high"  # 80%


def test_critical_warning_at_100_percent(svc):
    assert svc.quota_warning_level("free", 25) == "critical"
    assert svc.quota_warning_level("free", 30) == "critical"


def test_get_plan_via_service(svc):
    plan = svc.get_plan("pro")
    assert isinstance(plan, Plan)
    assert plan.code == "pro"
