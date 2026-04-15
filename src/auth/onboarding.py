"""Onboarding state machine for the self-serve hosted flow."""

# ---------------------------------------------------------------------------
# Onboarding progress states  (users.onboarding_status)
# ---------------------------------------------------------------------------

PENDING_EMAIL_VERIFICATION = "pending_email_verification"
PENDING_DB_CONNECTION = "pending_db_connection"
SETUP_COMPLETE = "setup_complete"

# ---------------------------------------------------------------------------
# Account states  (users.account_status)
# ---------------------------------------------------------------------------

ACCOUNT_ACTIVE = "active"
ACCOUNT_SUSPENDED = "suspended"
ACCOUNT_CLOSED = "closed"

ACCOUNT_STATES: frozenset[str] = frozenset({ACCOUNT_ACTIVE, ACCOUNT_SUSPENDED, ACCOUNT_CLOSED})
TERMINAL_ACCOUNT_STATES: frozenset[str] = frozenset({ACCOUNT_CLOSED})

# ---------------------------------------------------------------------------
# Billing states  (users.billing_status)
# ---------------------------------------------------------------------------

BILLING_FREE = "free"
BILLING_TRIALING = "trialing"
BILLING_ACTIVE_PAID = "active_paid"
BILLING_PAST_DUE = "past_due"
BILLING_CANCELED = "canceled"

# ---------------------------------------------------------------------------
# Backward-compat aliases  prefer ACCOUNT_* in new code
# ---------------------------------------------------------------------------

ACTIVE = ACCOUNT_ACTIVE
SUSPENDED = ACCOUNT_SUSPENDED
CLOSED = ACCOUNT_CLOSED

# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------

TRIGGER_EMAIL_VERIFIED = "email_verified"
TRIGGER_DB_SUBMITTED = "db_submitted"

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InvalidTransitionError(Exception):
    """Raised when (current_state, trigger) has no valid destination."""


# ---------------------------------------------------------------------------
# Next-step descriptions
# ---------------------------------------------------------------------------

_NEXT_STEP_DESCRIPTIONS: dict[str, str] = {
    PENDING_EMAIL_VERIFICATION: "Check your email and click the verification link.",
    PENDING_DB_CONNECTION: "Submit your database connection details.",
    SETUP_COMPLETE: "Setup complete. Create an API key to start querying.",
    ACCOUNT_ACTIVE: "Your account is active. You may use your API key.",
    ACCOUNT_SUSPENDED: "Account suspended. Contact support.",
    ACCOUNT_CLOSED: "Account closed.",
}


def get_next_step_description(status: str) -> str:
    """Return a human-readable instruction for the given onboarding or account status."""
    return _NEXT_STEP_DESCRIPTIONS.get(status, "Contact support for assistance.")


# ---------------------------------------------------------------------------
# State machine  (onboarding progress only)
# ---------------------------------------------------------------------------


def resolve_next_state(current_state: str, trigger: str) -> str:
    """Return the destination onboarding state for (current_state, trigger).

    Only handles onboarding progress transitions. Account-level state changes
    (suspend, close) are managed directly through UserStore.

    Raises InvalidTransitionError when the transition is not allowed.
    """
    if current_state == PENDING_EMAIL_VERIFICATION and trigger == TRIGGER_EMAIL_VERIFIED:
        return PENDING_DB_CONNECTION

    if current_state == PENDING_DB_CONNECTION and trigger == TRIGGER_DB_SUBMITTED:
        return SETUP_COMPLETE

    raise InvalidTransitionError(f"No transition from '{current_state}' on trigger '{trigger}'.")