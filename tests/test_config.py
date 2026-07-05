"""Unit tests for Settings validators in src.config."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config import Settings


def _base_kwargs(**overrides) -> dict:
    """Minimal kwargs to construct Settings without touching .env."""
    defaults = {
        "environment": "production",
        "auth_database_url": "postgresql://u:p@host/db",
        "credential_encryption_keys": "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXQ=",
        "registration_open": False,
        # An email backend is required outside development; provide one so the
        # baseline prod config is valid and tests can override it explicitly.
        "resend_api_key": "re_testkey",
        "resend_from_address": "noreply@example.com",
    }
    defaults.update(overrides)
    return defaults


class TestCheckOauthAudience:
    def test_oauth_only_without_audience_raises_in_production(self):
        with pytest.raises(ValidationError, match="OAUTH_AUDIENCE"):
            Settings(
                **_base_kwargs(
                    mcp_auth_mode="oauth_only",
                    oauth_issuer_url="https://auth.example.com/",
                    mcp_resource_url="https://app.example.com/mcp",
                    oauth_audience="",
                )
            )

    def test_hybrid_without_audience_raises_in_production(self):
        with pytest.raises(ValidationError, match="OAUTH_AUDIENCE"):
            Settings(
                **_base_kwargs(
                    mcp_auth_mode="hybrid",
                    oauth_issuer_url="https://auth.example.com/",
                    mcp_resource_url="https://app.example.com/mcp",
                    oauth_audience="",
                )
            )

    def test_oauth_only_with_audience_passes(self):
        s = Settings(
            **_base_kwargs(
                mcp_auth_mode="oauth_only",
                oauth_issuer_url="https://auth.example.com/",
                mcp_resource_url="https://app.example.com/mcp",
                oauth_audience="https://app.example.com/mcp",
            )
        )
        assert s.oauth_audience == "https://app.example.com/mcp"

    def test_api_key_only_without_audience_passes(self):
        s = Settings(**_base_kwargs(mcp_auth_mode="api_key_only", oauth_audience=""))
        assert s.mcp_auth_mode == "api_key_only"

    def test_oauth_only_without_audience_allowed_in_development(self):
        s = Settings(
            **_base_kwargs(
                environment="development",
                mcp_auth_mode="oauth_only",
                oauth_issuer_url="https://auth.example.com/",
                mcp_resource_url="https://app.example.com/mcp",
                oauth_audience="",
                # dev exempts credential_encryption_keys and registration_open too
                credential_encryption_keys="",
                registration_open=None,
            )
        )
        assert s.oauth_audience == ""


class TestEmailBackendRequired:
    def test_production_without_email_backend_raises(self):
        with pytest.raises(ValidationError, match="email backend"):
            Settings(
                **_base_kwargs(
                    resend_api_key="",
                    resend_from_address="",
                    smtp_host=None,
                )
            )

    def test_production_with_partial_resend_config_raises(self):
        # API key without a from address is not a usable Resend backend.
        with pytest.raises(ValidationError, match="email backend"):
            Settings(
                **_base_kwargs(
                    resend_api_key="re_testkey",
                    resend_from_address="",
                    smtp_host=None,
                )
            )

    def test_production_with_resend_passes(self):
        s = Settings(**_base_kwargs())  # resend configured by default
        assert s.email_backend_is_configured() is True

    def test_production_with_smtp_passes(self):
        s = Settings(
            **_base_kwargs(
                resend_api_key="",
                resend_from_address="",
                smtp_host="smtp.example.com",
            )
        )
        assert s.email_backend_is_configured() is True

    def test_development_without_email_backend_passes(self):
        s = Settings(
            **_base_kwargs(
                environment="development",
                credential_encryption_keys="",
                registration_open=None,
                resend_api_key="",
                resend_from_address="",
                smtp_host=None,
            )
        )
        assert s.email_backend_is_configured() is False
