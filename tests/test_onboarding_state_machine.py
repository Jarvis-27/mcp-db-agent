"""Unit tests for src/auth/onboarding.py — pure state machine logic, no DB."""

import pytest

from src.auth.onboarding import (
    ACTIVE,
    CLOSED,
    PENDING_BILLING,
    PENDING_DB_CONNECTION,
    PENDING_EMAIL_VERIFICATION,
    PENDING_MFA,
    PENDING_REVIEW,
    SUSPENDED,
    TRIGGER_ADMIN_APPROVED,
    TRIGGER_ADMIN_CLOSED,
    TRIGGER_ADMIN_SUSPENDED,
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
    from src.auth.onboarding import TRIGGER_BILLING_BYPASSED
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
# db_submitted → pending_review
# ---------------------------------------------------------------------------


def test_db_submitted_goes_to_pending_review():
    result = resolve_next_state(PENDING_DB_CONNECTION, TRIGGER_DB_SUBMITTED)
    assert result == PENDING_REVIEW


# ---------------------------------------------------------------------------
# Admin transitions
# ---------------------------------------------------------------------------


def test_admin_approved_on_pending_review_goes_to_active():
    result = resolve_next_state(PENDING_REVIEW, TRIGGER_ADMIN_APPROVED)
    assert result == ACTIVE


def test_admin_suspended_on_active_goes_to_suspended():
    result = resolve_next_state(ACTIVE, TRIGGER_ADMIN_SUSPENDED)
    assert result == SUSPENDED


def test_admin_closed_on_active_goes_to_closed():
    result = resolve_next_state(ACTIVE, TRIGGER_ADMIN_CLOSED)
    assert result == CLOSED


def test_admin_closed_on_suspended_goes_to_closed():
    result = resolve_next_state(SUSPENDED, TRIGGER_ADMIN_CLOSED)
    assert result == CLOSED


def test_admin_approved_on_suspended_reinstates_active():
    result = resolve_next_state(SUSPENDED, TRIGGER_ADMIN_APPROVED)
    assert result == ACTIVE


def test_admin_closed_on_pending_review():
    result = resolve_next_state(PENDING_REVIEW, TRIGGER_ADMIN_CLOSED)
    assert result == CLOSED


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------


def test_invalid_trigger_from_pending_db_connection_raises():
    with pytest.raises(InvalidTransitionError):
        resolve_next_state(PENDING_DB_CONNECTION, TRIGGER_EMAIL_VERIFIED)


def test_invalid_trigger_from_active_raises():
    with pytest.raises(InvalidTransitionError):
        resolve_next_state(ACTIVE, TRIGGER_EMAIL_VERIFIED)


def test_transition_from_closed_raises():
    with pytest.raises(InvalidTransitionError):
        resolve_next_state(CLOSED, TRIGGER_ADMIN_APPROVED)


def test_transition_from_closed_any_trigger_raises():
    with pytest.raises(InvalidTransitionError):
        resolve_next_state(CLOSED, TRIGGER_ADMIN_CLOSED)


def test_unknown_trigger_raises():
    with pytest.raises(InvalidTransitionError):
        resolve_next_state(PENDING_REVIEW, "unknown_trigger")


# ---------------------------------------------------------------------------
# Next step descriptions
# ---------------------------------------------------------------------------


def test_get_next_step_description_known_states():
    for state in [
        PENDING_EMAIL_VERIFICATION, PENDING_BILLING, PENDING_MFA,
        PENDING_DB_CONNECTION, PENDING_REVIEW, ACTIVE, SUSPENDED, CLOSED,
    ]:
        desc = get_next_step_description(state)
        assert isinstance(desc, str)
        assert len(desc) > 0


def test_get_next_step_description_unknown_state():
    desc = get_next_step_description("totally_unknown_state")
    assert "support" in desc.lower()
