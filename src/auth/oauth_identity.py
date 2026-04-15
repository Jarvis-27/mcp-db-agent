"""Resolve verified OAuth claims to a local :class:`UserConfig`.

After :class:`~src.auth.oauth_verifier.OAuthVerifier` confirms a bearer token
is cryptographically valid, this module maps the ``(issuer, subject)`` pair to
an existing local ``users`` row and applies the same account-health checks that
the API-key path uses.

Identity resolution always uses ``(issuer, subject)`` — never email alone.
Email may be captured for display purposes but is not the runtime key.
"""

from __future__ import annotations

import logging

from src.auth.oauth_verifier import OAuthClaims
from src.auth.onboarding import (
    ACCOUNT_ACTIVE,
    ACCOUNT_CLOSED,
    ACCOUNT_SUSPENDED,
    SETUP_COMPLETE,
)
from src.auth.user_store import UserConfig, UserStore

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OAuthIdentityError(Exception):
    """Raised when a verified OAuth identity cannot be resolved to a usable account."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class OAuthIdentityResolver:
    """Map a verified :class:`OAuthClaims` to a local :class:`UserConfig`.

    Failure cases — all raise :class:`OAuthIdentityError`:

    - No local user linked to ``(issuer, subject)``
    - Account suspended or closed
    - Onboarding not complete
    - No active database connected
    """

    def __init__(self, user_store: UserStore) -> None:
        self._store = user_store

    def resolve(self, claims: OAuthClaims) -> UserConfig:
        """Return the :class:`UserConfig` for *claims* or raise :class:`OAuthIdentityError`."""
        user_config = self._store.get_user_by_oauth_subject(claims.issuer, claims.subject)

        if user_config is None:
            raise OAuthIdentityError(
                "No local account is linked to this OAuth identity. "
                "Sign in to the web app and use 'Connect MCP account' to link first.",
                code="no_linked_account",
            )

        if user_config.account_status == ACCOUNT_SUSPENDED:
            raise OAuthIdentityError("Account is suspended.", code="account_suspended")

        if user_config.account_status == ACCOUNT_CLOSED:
            raise OAuthIdentityError("Account is closed.", code="account_closed")

        if user_config.account_status != ACCOUNT_ACTIVE:
            raise OAuthIdentityError(
                f"Account is not active (status: {user_config.account_status}).",
                code="account_inactive",
            )

        if user_config.onboarding_status != SETUP_COMPLETE:
            raise OAuthIdentityError(
                "Account setup is not complete. Finish onboarding before using MCP.",
                code="setup_incomplete",
            )

        if user_config.database_url is None:
            raise OAuthIdentityError(
                "No database is connected. Connect a database in the web app before using MCP.",
                code="no_database",
            )

        # Fire-and-forget: update last login timestamp (non-critical)
        try:
            self._store.update_oauth_last_login(claims.issuer, claims.subject)
        except Exception:
            log.debug("Failed to update oauth_last_login_at", exc_info=True)

        return user_config
