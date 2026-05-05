"""Unit tests for OAuthVerifier — all without real network calls.

We generate RSA key pairs in-memory and build toy JWTs to exercise every
validation code path.  No Auth0 or external IdP is contacted.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from src.auth.oauth_verifier import OAuthClaims, OAuthVerificationError, OAuthVerifier


# ---------------------------------------------------------------------------
# Key generation helpers
# ---------------------------------------------------------------------------


def _generate_rsa_key_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return private_key, public_key


def _private_pem(private_key) -> bytes:
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )


# ---------------------------------------------------------------------------
# Mock JWKS client
# ---------------------------------------------------------------------------


class _FakeSigningKey:
    """Minimal stand-in for the object returned by PyJWKClient.get_signing_key_from_jwt()."""

    def __init__(self, key) -> None:
        self.key = key  # raw cryptography public key used by jwt.decode()


class _MockJWKSClient:
    """Bypasses HTTP; returns a fixed public key for decoding."""

    def __init__(self, public_key) -> None:
        self._signing_key = _FakeSigningKey(public_key)

    def get_signing_key_from_jwt(self, token: str) -> _FakeSigningKey:
        return self._signing_key


# ---------------------------------------------------------------------------
# Verifier factory
# ---------------------------------------------------------------------------

_ISSUER = "https://test.example.com"
_AUDIENCE = "https://api.example.com/mcp"


def _make_verifier(
    private_key,
    public_key,
    *,
    issuer: str = _ISSUER,
    audience: str = _AUDIENCE,
    required_scopes: list[str] | None = None,
) -> OAuthVerifier:
    # None sentinel means "use default"; empty list means "no scopes required"
    scopes = ["mcp:access"] if required_scopes is None else required_scopes
    verifier = OAuthVerifier(
        issuer_url=issuer,
        audience=audience,
        required_scopes=scopes,
        jwks_url="https://test.example.com/.well-known/jwks.json",
    )
    # Inject mock JWKS client that returns the public key for this key pair
    verifier._jwks_client = _MockJWKSClient(public_key)
    return verifier


def _make_token(
    private_key,
    *,
    issuer: str = _ISSUER,
    subject: str = "oauth2|test-user-123",
    audience: str = _AUDIENCE,
    scope: str = "mcp:access",
    exp_offset: int = 3600,
    nbf_offset: int = 0,
    email: str | None = "user@example.com",
) -> str:
    now = int(time.time())
    payload: dict = {
        "iss": issuer,
        "sub": subject,
        "aud": audience,
        "exp": now + exp_offset,
        "iat": now,
        "scope": scope,
    }
    if nbf_offset:
        payload["nbf"] = now + nbf_offset
    if email:
        payload["email"] = email
    return jwt.encode(payload, _private_pem(private_key), algorithm="RS256")


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


def test_verify_returns_claims_for_valid_token():
    priv, pub = _generate_rsa_key_pair()
    verifier = _make_verifier(priv, pub)
    token = _make_token(priv)
    claims = verifier.verify(token)

    assert isinstance(claims, OAuthClaims)
    assert claims.issuer == _ISSUER
    assert claims.subject == "oauth2|test-user-123"
    assert "mcp:access" in claims.scopes
    assert claims.email == "user@example.com"
    assert claims.expires_at > int(time.time())


def test_verify_no_email_claim():
    priv, pub = _generate_rsa_key_pair()
    verifier = _make_verifier(priv, pub)
    token = _make_token(priv, email=None)
    claims = verifier.verify(token)
    assert claims.email is None


def test_verify_multiple_scopes():
    priv, pub = _generate_rsa_key_pair()
    verifier = _make_verifier(priv, pub, required_scopes=["mcp:access"])
    token = _make_token(priv, scope="openid email mcp:access profile")
    claims = verifier.verify(token)
    assert "mcp:access" in claims.scopes
    assert "openid" in claims.scopes


def test_verify_no_required_scopes():
    priv, pub = _generate_rsa_key_pair()
    verifier = _make_verifier(priv, pub, required_scopes=[])
    token = _make_token(priv, scope="")
    claims = verifier.verify(token)
    assert claims.scopes == frozenset()


# ---------------------------------------------------------------------------
# Rejection tests
# ---------------------------------------------------------------------------


def test_expired_token_raises():
    priv, pub = _generate_rsa_key_pair()
    verifier = _make_verifier(priv, pub)
    token = _make_token(priv, exp_offset=-60)  # beyond the verifier's 30s leeway
    with pytest.raises(OAuthVerificationError, match="expired"):
        verifier.verify(token)


def test_not_yet_valid_token_raises():
    priv, pub = _generate_rsa_key_pair()
    verifier = _make_verifier(priv, pub)
    token = _make_token(priv, nbf_offset=9999)  # not valid for a long time
    with pytest.raises(OAuthVerificationError, match="not yet valid"):
        verifier.verify(token)


def test_wrong_issuer_raises():
    priv, pub = _generate_rsa_key_pair()
    verifier = _make_verifier(priv, pub, issuer=_ISSUER)
    token = _make_token(priv, issuer="https://evil.example.com")
    with pytest.raises(OAuthVerificationError, match="issuer"):
        verifier.verify(token)


def test_wrong_audience_raises():
    priv, pub = _generate_rsa_key_pair()
    verifier = _make_verifier(priv, pub, audience=_AUDIENCE)
    token = _make_token(priv, audience="https://other.example.com/api")
    with pytest.raises(OAuthVerificationError, match="audience"):
        verifier.verify(token)


def test_missing_sub_raises():
    priv, pub = _generate_rsa_key_pair()
    verifier = _make_verifier(priv, pub)
    now = int(time.time())
    payload = {
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "exp": now + 3600,
        "iat": now,
        "scope": "mcp:access",
        # "sub" deliberately omitted
    }
    token = jwt.encode(payload, _private_pem(priv), algorithm="RS256")
    with pytest.raises(OAuthVerificationError, match="sub"):
        verifier.verify(token)


def test_missing_required_scope_raises():
    priv, pub = _generate_rsa_key_pair()
    verifier = _make_verifier(priv, pub, required_scopes=["mcp:access", "mcp:write"])
    token = _make_token(priv, scope="mcp:access")  # missing mcp:write
    with pytest.raises(OAuthVerificationError, match="scope"):
        verifier.verify(token)


def test_wrong_signing_key_raises():
    """Token signed with key2 but verifier uses key1's public key → signature failure."""
    priv1, pub1 = _generate_rsa_key_pair()
    priv2, pub2 = _generate_rsa_key_pair()
    # Verifier expects pub1, but token is signed with priv2
    verifier = _make_verifier(priv1, pub1)
    token = _make_token(priv2)
    with pytest.raises(OAuthVerificationError):
        verifier.verify(token)


def test_malformed_token_raises():
    priv, pub = _generate_rsa_key_pair()
    verifier = _make_verifier(priv, pub)
    with pytest.raises(OAuthVerificationError):
        verifier.verify("not.a.jwt")


# ---------------------------------------------------------------------------
# JWKS error propagation
# ---------------------------------------------------------------------------


def test_jwks_fetch_failure_raises():
    class _FailingJWKSClient:
        def get_signing_key_from_jwt(self, token):
            from jwt import PyJWKClientError

            raise PyJWKClientError("connection refused")

    priv, pub = _generate_rsa_key_pair()
    verifier = _make_verifier(priv, pub)
    verifier._jwks_client = _FailingJWKSClient()
    token = _make_token(priv)
    with pytest.raises(OAuthVerificationError, match="JWKS"):
        verifier.verify(token)


# ---------------------------------------------------------------------------
# Trailing-slash normalisation
# ---------------------------------------------------------------------------


def test_issuer_trailing_slash_is_normalised():
    """OAuthVerifier strips trailing slashes from issuer_url for comparison."""
    priv, pub = _generate_rsa_key_pair()
    # Verifier created with trailing slash
    verifier = OAuthVerifier(
        issuer_url=f"{_ISSUER}/",
        audience=_AUDIENCE,
        required_scopes=["mcp:access"],
        jwks_url="https://test.example.com/.well-known/jwks.json",
    )
    verifier._jwks_client = _MockJWKSClient(pub)
    # Token uses issuer without trailing slash
    token = _make_token(priv, issuer=_ISSUER)
    claims = verifier.verify(token)
    assert claims.issuer == _ISSUER
