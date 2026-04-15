"""Entitlement evaluation service.

Provides server-side quota and limit checks keyed on the user's plan_code.
All decisions are evaluated server-side — never trust client-supplied plan data.
"""

from dataclasses import dataclass

from src.entitlements.plans import Plan, get_plan


@dataclass(frozen=True)
class EntitlementResult:
    allowed: bool
    limit: int
    current: int
    plan_code: str
    reason: str | None = None


class EntitlementService:
    """Evaluate whether a user action is within their plan entitlements."""

    def get_plan(self, plan_code: str) -> Plan:
        return get_plan(plan_code)

    def check_query_quota(self, plan_code: str, current_daily_count: int) -> EntitlementResult:
        """Check if another ask_database call is within the daily limit."""
        plan = get_plan(plan_code)
        allowed = current_daily_count < plan.ask_database_per_day
        return EntitlementResult(
            allowed=allowed,
            limit=plan.ask_database_per_day,
            current=current_daily_count,
            plan_code=plan.code,
            reason=None if allowed else "daily_quota_exceeded",
        )

    def check_api_key_quota(self, plan_code: str, current_key_count: int) -> EntitlementResult:
        """Check if the user can create another API key."""
        plan = get_plan(plan_code)
        allowed = current_key_count < plan.max_api_keys
        return EntitlementResult(
            allowed=allowed,
            limit=plan.max_api_keys,
            current=current_key_count,
            plan_code=plan.code,
            reason=None if allowed else "api_key_limit_reached",
        )

    def check_database_quota(self, plan_code: str, current_db_count: int) -> EntitlementResult:
        """Check if the user can connect another database."""
        plan = get_plan(plan_code)
        allowed = current_db_count < plan.max_active_databases
        return EntitlementResult(
            allowed=allowed,
            limit=plan.max_active_databases,
            current=current_db_count,
            plan_code=plan.code,
            reason=None if allowed else "database_limit_reached",
        )

    def quota_warning_level(self, plan_code: str, current_daily_count: int) -> str | None:
        """Return a warning level string if the user is approaching their daily quota.

        Returns 'critical' at 100%, 'high' at 80%, 'medium' at 50%, None otherwise.
        """
        plan = get_plan(plan_code)
        if plan.ask_database_per_day == 0:
            return None
        pct = current_daily_count / plan.ask_database_per_day
        if pct >= 1.0:
            return "critical"
        if pct >= 0.8:
            return "high"
        if pct >= 0.5:
            return "medium"
        return None
