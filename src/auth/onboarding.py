"""Onboarding state machine — pure logic, no database dependencies.

All state transitions and trigger constants are defined here so that the
UserStore, API layer, and tests share a single authoritative definition.
"""

# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------

PENDING_EMAIL_VERIFICATION = "pending_email_verification"
PENDING_BILLING = "pending_billing"
PENDING_MFA = "pending_mfa"
PENDING_DB_CONNECTION = "pending_db_connection"
PENDING_REVIEW = "pending_review"
ACTIVE = "active"
SUSPENDED = "suspended"
CLOSED = "closed"

ALL_STATES: frozenset[str] = frozenset(
    {
        PENDING_EMAIL_VERIFICATION,
        PENDING_BILLING,
        PENDING_MFA,
        PENDING_DB_CONNECTION,
        PENDING_REVIEW,
        ACTIVE,
        SUSPENDED,
        CLOSED,
    }
)

TERMINAL_STATES: frozenset[str] = frozenset({CLOSED})

# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------

TRIGGER_EMAIL_VERIFIED = "email_verified"
TRIGGER_BILLING_PAID = "billing_paid"         # Phase 1 (Stripe webhook)
TRIGGER_MFA_ENROLLED = "mfa_enrolled"         # Phase 1 (Auth0)
TRIGGER_BILLING_BYPASSED = "billing_bypassed" # auto-advance when gate disabled
TRIGGER_MFA_BYPASSED = "mfa_bypassed"         # auto-advance when gate disabled
TRIGGER_DB_SUBMITTED = "db_submitted"
TRIGGER_ADMIN_APPROVED = "admin_approved"
TRIGGER_ADMIN_SUSPENDED = "admin_suspended"
TRIGGER_ADMIN_CLOSED = "admin_closed"

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InvalidTransitionError(Exception):
    """Raised when (current_state, trigger) has no valid destination."""


# ---------------------------------------------------------------------------
# Next-step descriptions (replaces inline dict in app.py)
# ---------------------------------------------------------------------------

_NEXT_STEP_DESCRIPTIONS: dict[str, str] = {
    PENDING_EMAIL_VERIFICATION: "Check your email and click the verification link.",
    PENDING_BILLING: "Complete your subscription or free trial setup.",
    PENDING_MFA: "Enroll a passkey or MFA device.",
    PENDING_DB_CONNECTION: "Submit your database connection details.",
    PENDING_REVIEW: "Your account is under review. We will contact you shortly.",
    ACTIVE: "Your account is active. You may use your API key.",
    SUSPENDED: "Account suspended. Contact support.",
    CLOSED: "Account closed.",
}


def get_next_step_description(status: str) -> str:
    """Return a human-readable instruction for the given onboarding status."""
    return _NEXT_STEP_DESCRIPTIONS.get(status, "Contact support for assistance.")


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


def resolve_next_state(
    current_state: str,
    trigger: str,
    billing_gate_enabled: bool = False,
    mfa_gate_enabled: bool = False,
) -> str:
    """Return the destination state for (current_state, trigger).

    Gate flags control whether billing and MFA steps are required:
    - billing_gate_enabled: if False, billing step is auto-skipped
    - mfa_gate_enabled: if False, MFA step is auto-skipped

    Raises InvalidTransitionError when the transition is not allowed.
    """
    if current_state in TERMINAL_STATES:
        raise InvalidTransitionError(
            f"State '{current_state}' is terminal — no further transitions allowed."
        )

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
    # pending_billing
    # ------------------------------------------------------------------
    if current_state == PENDING_BILLING:
        if trigger in (TRIGGER_BILLING_PAID, TRIGGER_BILLING_BYPASSED):
            if mfa_gate_enabled:
                return PENDING_MFA
            return PENDING_DB_CONNECTION

    # ------------------------------------------------------------------
    # pending_mfa
    # ------------------------------------------------------------------
    if current_state == PENDING_MFA:
        if trigger in (TRIGGER_MFA_ENROLLED, TRIGGER_MFA_BYPASSED):
            return PENDING_DB_CONNECTION

    # ------------------------------------------------------------------
    # pending_db_connection
    # ------------------------------------------------------------------
    if current_state == PENDING_DB_CONNECTION:
        if trigger == TRIGGER_DB_SUBMITTED:
            return PENDING_REVIEW

    # ------------------------------------------------------------------
    # pending_review
    # ------------------------------------------------------------------
    if current_state == PENDING_REVIEW:
        if trigger == TRIGGER_ADMIN_APPROVED:
            return ACTIVE
        if trigger == TRIGGER_ADMIN_CLOSED:
            return CLOSED

    # ------------------------------------------------------------------
    # active
    # ------------------------------------------------------------------
    if current_state == ACTIVE:
        if trigger == TRIGGER_ADMIN_SUSPENDED:
            return SUSPENDED
        if trigger == TRIGGER_ADMIN_CLOSED:
            return CLOSED

    # ------------------------------------------------------------------
    # suspended
    # ------------------------------------------------------------------
    if current_state == SUSPENDED:
        if trigger == TRIGGER_ADMIN_APPROVED:
            return ACTIVE
        if trigger == TRIGGER_ADMIN_CLOSED:
            return CLOSED

    raise InvalidTransitionError(
        f"No transition from '{current_state}' on trigger '{trigger}'."
    )
