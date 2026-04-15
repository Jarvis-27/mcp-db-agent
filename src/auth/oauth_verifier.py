"""OAuth 2.1 bearer-token verification for the /mcp resource server.

Validates JWTs from any standards-compliant authorization server using JWKS
discovery.  Returns a normalized :class:`OAuthClaims` object on success and
raises :class:`OAuthVerificationError` on any failure.

Design notes
------------
- Provider-agnostic: works with any issuer that publishes a JWKS endpoint.
- Uses PyJWT's PyJWKClient for JWKS fetching and key caching.
- Signature algorithms RS256 and ES256 are accepted; HS256 is rejected.
- Audience verification is skipped when ``audience`` is empty (useful in
  development when no API resource is configured in the IdP).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import jwt
from jwt import PyJWKClient, PyJWKClientError

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OAuthClaims:
    """Normalized, verified claims extracted from a bearer access token."""

    issuer: str
    subject: str
    scopes: frozenset[str]
    expires_at: int  # Unix timestamp
    email: str | None = None
    audience: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OAuthVerificationError(Exception):
    """Raised when a bearer token fails any verification check."""


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------


class OAuthVerifier:
    """Validate OAuth 2.1 bearer tokens against a remote JWKS endpoint.

    Parameters
    ----------
    issuer_url:
        Expected ``iss`` claim value (authorization server base URL).
        Trailing slash is stripped before comparison so that
        ``https://example.auth0.com/`` and ``https://example.auth0.com`` match.
    audience:
        Expected ``aud`` claim value.  When empty, audience verification is
        skipped — appropriate for development environments.
    required_scopes:
        Scopes that **must** be present in the token.  An empty list means any
        authenticated token is accepted.
    jwks_url:
        Optional override for the JWKS endpoint.  Defaults to
        ``{issuer_url}/.well-known/jwks.json``.
    jwks_cache_ttl:
        Seconds the JWKS key set is cached before re-fetching.
    """

    _ACCEPTED_ALGORITHMS = ["RS256", "ES256"]

    def __init__(
        self,
        *,
        issuer_url: str,
        audience: str = "",
        required_scopes: list[str] | None = None,
        jwks_url: str = "",
        jwks_cache_ttl: int = 300,
    ) -> None:
        self._issuer = issuer_url.rstrip("/")
        self._audience = audience
        self._required_scopes: frozenset[str] = frozenset(required_scopes or [])
        effective_jwks = jwks_url.strip() or f"{self._issuer}/.well-known/jwks.json"
        self._jwks_client = PyJWKClient(
            effective_jwks,
            cache_jwk_set=True,
            lifespan=jwks_cache_ttl,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def verify(self, raw_token: str) -> OAuthClaims:
        """Verify *raw_token* and return normalized claims.

        Raises :class:`OAuthVerificationError` if anything is wrong.
        Never logs the raw token value.
        """
        signing_key = self._fetch_signing_key(raw_token)
        payload = self._decode_token(raw_token, signing_key)
        return self._extract_claims(payload)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_signing_key(self, raw_token: str):
        try:
            return self._jwks_client.get_signing_key_from_jwt(raw_token)
        except PyJWKClientError as exc:
            raise OAuthVerificationError(f"JWKS key fetch failed: {exc}") from exc
        except Exception as exc:
            raise OAuthVerificationError(f"Unexpected error fetching JWKS: {exc}") from exc

    def _decode_token(self, raw_token: str, signing_key) -> dict:
        decode_options: dict[str, bool] = {
            "verify_exp": True,
            "verify_nbf": True,
            "verify_iss": True,
            "verify_aud": bool(self._audience),
        }
        try:
            payload: dict = jwt.decode(
                raw_token,
                signing_key.key,
                algorithms=self._ACCEPTED_ALGORITHMS,
                issuer=self._issuer,
                audience=self._audience if self._audience else None,
                options=decode_options,
            )
        except jwt.ExpiredSignatureError:
            raise OAuthVerificationError("Token has expired")
        except jwt.ImmatureSignatureError:
            raise OAuthVerificationError("Token is not yet valid (nbf check failed)")
        except jwt.InvalidIssuerError:
            raise OAuthVerificationError(
                f"Token issuer does not match expected issuer '{self._issuer}'"
            )
        except jwt.InvalidAudienceError:
            raise OAuthVerificationError(
                f"Token audience does not match expected audience '{self._audience}'"
            )
        except jwt.InvalidAlgorithmError:
            raise OAuthVerificationError("Token uses an unsupported signing algorithm")
        except jwt.DecodeError as exc:
            raise OAuthVerificationError(f"Token is malformed: {exc}") from exc
        except jwt.InvalidTokenError as exc:
            raise OAuthVerificationError(f"Token validation failed: {exc}") from exc
        return payload

    def _extract_claims(self, payload: dict) -> OAuthClaims:
        subject = payload.get("sub")
        if not subject:
            raise OAuthVerificationError("Token is missing the 'sub' claim")

        # Scopes may be a space-delimited string (RFC 6749) or a list (some providers)
        raw_scope = payload.get("scope", "")
        if isinstance(raw_scope, list):
            scopes: frozenset[str] = frozenset(raw_scope)
        else:
            scopes = frozenset(raw_scope.split()) if raw_scope else frozenset()

        missing = self._required_scopes - scopes
        if missing:
            raise OAuthVerificationError(
                f"Token is missing required scope(s): {', '.join(sorted(missing))}"
            )

        raw_aud = payload.get("aud")
        if isinstance(raw_aud, list):
            audience: tuple[str, ...] = tuple(raw_aud)
        elif raw_aud:
            audience = (str(raw_aud),)
        else:
            audience = ()

        return OAuthClaims(
            issuer=str(payload.get("iss", self._issuer)),
            subject=str(subject),
            scopes=scopes,
            expires_at=int(payload.get("exp", int(time.time()) + 3600)),
            email=payload.get("email") or None,
            audience=audience,
        )
