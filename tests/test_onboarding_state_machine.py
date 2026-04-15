"""Unit tests for src/auth/onboarding.py - pure state machine logic, no DB."""

import pytest

from src.auth.onboarding import (
    ACCOUNT_ACTIVE,
    ACCOUNT_CLOSED,
    ACCOUNT_SUSPENDED,
    PENDING_DB_CONNECTION,
    PENDING_EMAIL_VERIFICATION,
    SETUP_COMPLETE,
    TRIGGER_DB_SUBMITTED,
    TRIGGER_EMAIL_VERIFIED,
    InvalidTransitionError,
    get_next_step_description,
    resolve_next_state,
)


# ---------------------------------------------------------------------------
# Email-verified transitions
# ---------------------------------------------------------------------------


def test_email_verified_goes_to_pending_db_connection():
    result = resolve_next_state(PENDING_EMAIL_VERIFICATION, TRIGGER_EMAIL_VERIFIED)
    assert result == PENDING_DB_CONNECTION


# ---------------------------------------------------------------------------
# db_submitted -> setup_complete  (self-serve activation, no pending_review)
# ---------------------------------------------------------------------------


def test_db_submitted_goes_to_setup_complete():
    """Core invariant: DB submission activates directly, no admin review."""
    result = resolve_next_state(PENDING_DB_CONNECTION, TRIGGER_DB_SUBMITTED)
    assert result == SETUP_COMPLETE


def test_db_submitted_never_goes_to_pending_review():
    result = resolve_next_state(PENDING_DB_CONNECTION, TRIGGER_DB_SUBMITTED)
    assert result != "pending_review"


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
        resolve_next_state(PENDING_DB_CONNECTION, "unknown_trigger")


# ---------------------------------------------------------------------------
# Account state constants are distinct from onboarding states
# ---------------------------------------------------------------------------


def test_account_state_constants_are_correct():
    assert ACCOUNT_ACTIVE == "active"
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
        PENDING_DB_CONNECTION,
        SETUP_COMPLETE,
        ACCOUNT_ACTIVE,
        ACCOUNT_SUSPENDED,
        ACCOUNT_CLOSED,
    ]:
        desc = get_next_step_description(state)
        assert isinstance(desc, str)
        assert len(desc) > 0


def test_get_next_step_description_unknown_state():
    desc = get_next_step_description("totally_unknown_state")
    assert "support" in desc.lower()