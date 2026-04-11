"""Onboarding state machine — pure logic, no database dependencies.

PHASE 1 REFACTOR: The status model is now split into two independent dimensions:

  onboarding_status  (tenants.status column):
      pending_email_verification → pending_db_connection → setup_complete
      pending_review is an optional admin-triggered risk hold, NOT the default path.

  account_status  (tenants.account_status column):
      active | restricted | suspended | closed
      Managed directly by UserStore — not by this state machine.
"""

# ---------------------------------------------------------------------------
# Onboarding progress states  (tenants.status)
# ---------------------------------------------------------------------------

PENDING_EMAIL_VERIFICATION = "pending_email_verification"
PENDING_DB_CONNECTION = "pending_db_connection"
SETUP_COMPLETE = "setup_complete"

# Optional gate states — only reached when billing_gate_enabled / mfa_gate_enabled
PENDING_BILLING = "pending_billing"
PENDING_MFA = "pending_mfa"

# Admin-triggered risk hold.  NOT on the self-serve path.
PENDING_REVIEW = "pending_review"

# ---------------------------------------------------------------------------
# Account states  (tenants.account_status)
# ---------------------------------------------------------------------------

ACCOUNT_ACTIVE = "active"
ACCOUNT_RESTRICTED = "restricted"
ACCOUNT_SUSPENDED = "suspended"
ACCOUNT_CLOSED = "closed"

ACCOUNT_STATES: frozenset[str] = frozenset(
    {ACCOUNT_ACTIVE, ACCOUNT_RESTRICTED, ACCOUNT_SUSPENDED, ACCOUNT_CLOSED}
)
TERMINAL_ACCOUNT_STATES: frozenset[str] = frozenset({ACCOUNT_CLOSED})

# ---------------------------------------------------------------------------
# Billing states  (tenants.billing_status)
# ---------------------------------------------------------------------------

BILLING_FREE = "free"
BILLING_TRIALING = "trialing"
BILLING_ACTIVE_PAID = "active_paid"
BILLING_PAST_DUE = "past_due"
BILLING_CANCELED = "canceled"

# ---------------------------------------------------------------------------
# Backward-compat aliases — prefer ACCOUNT_* in new code
# ---------------------------------------------------------------------------

ACTIVE = ACCOUNT_ACTIVE
SUSPENDED = ACCOUNT_SUSPENDED
CLOSED = ACCOUNT_CLOSED

# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------

TRIGGER_EMAIL_VERIFIED = "email_verified"
TRIGGER_DB_SUBMITTED = "db_submitted"
TRIGGER_BILLING_PAID = "billing_paid"
TRIGGER_BILLING_BYPASSED = "billing_bypassed"
TRIGGER_MFA_ENROLLED = "mfa_enrolled"
TRIGGER_MFA_BYPASSED = "mfa_bypassed"

# Informational — account-level changes go through UserStore, not this machine
TRIGGER_ADMIN_APPROVED = "admin_approved"
TRIGGER_ADMIN_SUSPENDED = "admin_suspended"
TRIGGER_ADMIN_CLOSED = "admin_closed"

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
    PENDING_BILLING: "Complete your subscription or free trial setup.",
    PENDING_MFA: "Enroll a passkey or MFA device.",
    PENDING_DB_CONNECTION: "Submit your database connection details.",
    SETUP_COMPLETE: "Setup complete. Create an API key to start querying.",
    PENDING_REVIEW: "Your account is under review. We will contact you shortly.",
    ACCOUNT_ACTIVE: "Your account is active. You may use your API key.",
    ACCOUNT_RESTRICTED: "Your account is restricted. Contact support.",
    ACCOUNT_SUSPENDED: "Account suspended. Contact support.",
    ACCOUNT_CLOSED: "Account closed.",
}


def get_next_step_description(status: str) -> str:
    """Return a human-readable instruction for the given onboarding or account status."""
    return _NEXT_STEP_DESCRIPTIONS.get(status, "Contact support for assistance.")


# ---------------------------------------------------------------------------
# State machine  (onboarding progress only)
# ---------------------------------------------------------------------------


def resolve_next_state(
    current_state: str,
    trigger: str,
    billing_gate_enabled: bool = False,
    mfa_gate_enabled: bool = False,
) -> str:
    """Return the destination onboarding state for (current_state, trigger).

    Only handles onboarding progress transitions.  Account-level state changes
    (suspend, restrict, close) are managed directly through UserStore.

    Raises InvalidTransitionError when the transition is not allowed.
    """
    # ------------------------------------------------------------------
    # pending_email_verification
    # ------------------------------------------------------------------
    if current_state == PENDING_EMAIL_VERIFICATION:
        if trigger == TRIGGER_EMAIL_VERIFIED:
            if billing_gate_enabled:
                return PENDING_BILLING
            if mfa_gate_enabled:
                return PENDING_MFA
            return PENDING_DB_CONNECTION

    # ------------------------------------------------------------------
    # pending_billing  (optional gate)
    # ------------------------------------------------------------------
    if current_state == PENDING_BILLING:
        if trigger in (TRIGGER_BILLING_PAID, TRIGGER_BILLING_BYPASSED):
            if mfa_gate_enabled:
                return PENDING_MFA
            return PENDING_DB_CONNECTION

    # ------------------------------------------------------------------
    # pending_mfa  (optional gate)
    # ------------------------------------------------------------------
    if current_state == PENDING_MFA:
        if trigger in (TRIGGER_MFA_ENROLLED, TRIGGER_MFA_BYPASSED):
            return PENDING_DB_CONNECTION

    # ------------------------------------------------------------------
    # pending_db_connection
    # Self-serve path: go directly to setup_complete — no admin review required.
    # ------------------------------------------------------------------
    if current_state == PENDING_DB_CONNECTION:
        if trigger == TRIGGER_DB_SUBMITTED:
            return SETUP_COMPLETE

    # ------------------------------------------------------------------
    # pending_review  (admin risk hold only)
    # Admin can clear the hold by approving.
    # ------------------------------------------------------------------
    if current_state == PENDING_REVIEW:
        if trigger == TRIGGER_ADMIN_APPROVED:
            return SETUP_COMPLETE

    raise InvalidTransitionError(f"No transition from '{current_state}' on trigger '{trigger}'.")
