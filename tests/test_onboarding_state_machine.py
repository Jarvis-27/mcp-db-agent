"""Unit tests for src/auth/onboarding.py — pure state machine logic, no DB."""

import pytest

from src.auth.onboarding import (
    ACCOUNT_ACTIVE,
    ACCOUNT_CLOSED,
    ACCOUNT_RESTRICTED,
    ACCOUNT_SUSPENDED,
    PENDING_BILLING,
    PENDING_DB_CONNECTION,
    PENDING_EMAIL_VERIFICATION,
    PENDING_MFA,
    PENDING_REVIEW,
    SETUP_COMPLETE,
    TRIGGER_ADMIN_APPROVED,
    TRIGGER_BILLING_BYPASSED,
    TRIGGER_BILLING_PAID,
    TRIGGER_DB_SUBMITTED,
    TRIGGER_EMAIL_VERIFIED,
    TRIGGER_MFA_ENROLLED,
    InvalidTransitionError,
    get_next_step_description,
    resolve_next_state,
)


# ---------------------------------------------------------------------------
# Email-verified transitions (gate combos)
# ---------------------------------------------------------------------------


def test_email_verified_no_gates_goes_to_pending_db_connection():
    result = resolve_next_state(
        PENDING_EMAIL_VERIFICATION,
        TRIGGER_EMAIL_VERIFIED,
        billing_gate_enabled=False,
        mfa_gate_enabled=False,
    )
    assert result == PENDING_DB_CONNECTION


def test_email_verified_billing_gate_on_goes_to_pending_billing():
    result = resolve_next_state(
        PENDING_EMAIL_VERIFICATION,
        TRIGGER_EMAIL_VERIFIED,
        billing_gate_enabled=True,
        mfa_gate_enabled=False,
    )
    assert result == PENDING_BILLING


def test_email_verified_mfa_gate_only_goes_to_pending_mfa():
    result = resolve_next_state(
        PENDING_EMAIL_VERIFICATION,
        TRIGGER_EMAIL_VERIFIED,
        billing_gate_enabled=False,
        mfa_gate_enabled=True,
    )
    assert result == PENDING_MFA


def test_email_verified_both_gates_billing_wins():
    """When both gates are on, billing gate takes priority."""
    result = resolve_next_state(
        PENDING_EMAIL_VERIFICATION,
        TRIGGER_EMAIL_VERIFIED,
        billing_gate_enabled=True,
        mfa_gate_enabled=True,
    )
    assert result == PENDING_BILLING


# ---------------------------------------------------------------------------
# Billing → MFA / db_connection transitions
# ---------------------------------------------------------------------------


def test_billing_paid_mfa_gate_on_goes_to_pending_mfa():
    result = resolve_next_state(
        PENDING_BILLING,
        TRIGGER_BILLING_PAID,
        mfa_gate_enabled=True,
    )
    assert result == PENDING_MFA


def test_billing_paid_mfa_gate_off_goes_to_pending_db_connection():
    result = resolve_next_state(
        PENDING_BILLING,
        TRIGGER_BILLING_PAID,
        mfa_gate_enabled=False,
    )
    assert result == PENDING_DB_CONNECTION


def test_billing_bypassed_same_as_billing_paid():
    result = resolve_next_state(PENDING_BILLING, TRIGGER_BILLING_BYPASSED)
    assert result == PENDING_DB_CONNECTION


# ---------------------------------------------------------------------------
# MFA → db_connection
# ---------------------------------------------------------------------------


def test_mfa_enrolled_goes_to_pending_db_connection():
    result = resolve_next_state(PENDING_MFA, TRIGGER_MFA_ENROLLED)
    assert result == PENDING_DB_CONNECTION


def test_mfa_bypassed_goes_to_pending_db_connection():
    from src.auth.onboarding import TRIGGER_MFA_BYPASSED

    result = resolve_next_state(PENDING_MFA, TRIGGER_MFA_BYPASSED)
    assert result == PENDING_DB_CONNECTION


# ---------------------------------------------------------------------------
# db_submitted → setup_complete  (self-serve activation, no pending_review)
# ---------------------------------------------------------------------------


def test_db_submitted_goes_to_setup_complete():
    """Core Phase 1 invariant: DB submission activates directly, no admin review."""
    result = resolve_next_state(PENDING_DB_CONNECTION, TRIGGER_DB_SUBMITTED)
    assert result == SETUP_COMPLETE


def test_db_submitted_never_goes_to_pending_review():
    result = resolve_next_state(PENDING_DB_CONNECTION, TRIGGER_DB_SUBMITTED)
    assert result != PENDING_REVIEW


# ---------------------------------------------------------------------------
# pending_review (admin risk hold) → setup_complete on admin approval
# ---------------------------------------------------------------------------


def test_admin_approved_on_pending_review_goes_to_setup_complete():
    """Admin clears a risk hold by approving; tenant returns to setup_complete."""
    result = resolve_next_state(PENDING_REVIEW, TRIGGER_ADMIN_APPROVED)
    assert result == SETUP_COMPLETE


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------


def test_invalid_trigger_from_pending_db_connection_raises():
    with pytest.raises(InvalidTransitionError):
        resolve_next_state(PENDING_DB_CONNECTION, TRIGGER_EMAIL_VERIFIED)


def test_invalid_trigger_from_setup_complete_raises():
    with pytest.raises(InvalidTransitionError):
        resolve_next_state(SETUP_COMPLETE, TRIGGER_EMAIL_VERIFIED)


def test_unknown_trigger_raises():
    with pytest.raises(InvalidTransitionError):
        resolve_next_state(PENDING_REVIEW, "unknown_trigger")


# ---------------------------------------------------------------------------
# Account state constants are distinct from onboarding states
# ---------------------------------------------------------------------------


def test_account_state_constants_are_correct():
    assert ACCOUNT_ACTIVE == "active"
    assert ACCOUNT_RESTRICTED == "restricted"
    assert ACCOUNT_SUSPENDED == "suspended"
    assert ACCOUNT_CLOSED == "closed"


def test_setup_complete_constant_is_correct():
    assert SETUP_COMPLETE == "setup_complete"


# ---------------------------------------------------------------------------
# Next step descriptions
# ---------------------------------------------------------------------------


def test_get_next_step_description_known_states():
    for state in [
        PENDING_EMAIL_VERIFICATION,
        PENDING_BILLING,
        PENDING_MFA,
        PENDING_DB_CONNECTION,
        SETUP_COMPLETE,
        PENDING_REVIEW,
        ACCOUNT_ACTIVE,
        ACCOUNT_RESTRICTED,
        ACCOUNT_SUSPENDED,
        ACCOUNT_CLOSED,
    ]:
        desc = get_next_step_description(state)
        assert isinstance(desc, str)
        assert len(desc) > 0


def test_get_next_step_description_unknown_state():
    desc = get_next_step_description("totally_unknown_state")
    assert "support" in desc.lower()
