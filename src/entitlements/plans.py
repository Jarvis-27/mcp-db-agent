"""Plan definitions for the free and pro tiers.

Quotas frozen in Phase 0:
  free — 25 ask_database/day, 1 API key, 1 active database
  pro  — 500 ask_database/day, 5 API keys, 2 active databases
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    code: str
    display_name: str
    ask_database_per_day: int
    max_api_keys: int
    max_active_databases: int


FREE_PLAN = Plan(
    code="free",
    display_name="Free",
    ask_database_per_day=25,
    max_api_keys=1,
    max_active_databases=1,
)

PRO_PLAN = Plan(
    code="pro",
    display_name="Pro",
    ask_database_per_day=500,
    max_api_keys=5,
    max_active_databases=2,
)

_PLANS: dict[str, Plan] = {
    FREE_PLAN.code: FREE_PLAN,
    PRO_PLAN.code: PRO_PLAN,
}


def get_plan(code: str) -> Plan:
    """Return the Plan for the given code, defaulting to FREE_PLAN for unknown codes."""
    return _PLANS.get(code, FREE_PLAN)
