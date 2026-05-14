from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class UserSettings:
    """Per-request LLM + query settings. Satisfies the attribute interface expected
    by SQLGenerator, SQLExecutor, and SelfCorrector without coupling them to the
    global Settings singleton."""

    llm_provider: str
    anthropic_api_key: str
    groq_api_key: str
    claude_model: str
    groq_model: str
    max_query_rows: int
    query_timeout_seconds: int
    max_self_correction_retries: int
    max_llm_chars_per_request: int = 40_000


_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    # ── LLM configuration ─────────────────────────────────────────────
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    llm_provider: str = ""
    claude_model: str = "claude-sonnet-4-6"
    groq_model: str = "llama-3.3-70b-versatile"
    max_query_rows: int = 100
    query_timeout_seconds: int = 30
    max_self_correction_retries: int = 3
    # Grace window for in-flight queries to drain on shutdown (G10). After
    # this many seconds the lifespan cancels still-active request tasks so
    # their CancelledError handlers can log terminal query_history rows.
    shutdown_grace_period_seconds: float = 30.0
    # Soft per-request LLM cost ceiling (G6). Counted as prompt+response characters;
    # at ~4 chars/token this is ≈ 10k tokens. SelfCorrector aborts when exceeded.
    max_llm_chars_per_request: int = 40_000
    # Per-API-key burst limit applied inside ask_database (G5). Sliding-window
    # counters live in-process; multi-worker deployments will multiply the cap
    # until a shared store is wired up — see CLAUDE.md "Rate-limiter scope".
    mcp_burst_capacity: int = 30
    mcp_burst_window_seconds: float = 60.0

    # ── Hosted account mode ────────────────────────────────────────────
    environment: Literal["development", "staging", "production"] = "development"
    auth_database_url: str = "sqlite:///./auth.db"
    credential_encryption_keys: str = ""  # comma-separated; first is the encryption key
    registration_open: bool | None = None  # None = not explicitly set → treated as False
    allow_sqlite_user_dbs: bool = False  # NEVER true in prod
    sqlite_user_db_dir: str = ""  # directory where user SQLite files are permitted
    extra_blocked_cidrs: str = ""  # comma-separated; e.g. "10.20.30.0/24,..."
    trusted_proxy_ips: str = "127.0.0.1"  # passed to uvicorn forwarded_allow_ips
    port: int = 8000
    cors_allow_origins: list[str] = []  # empty = closed
    max_request_bytes: int = 65536
    query_pool_size: int = 64  # ThreadPoolExecutor for SQLExecutor
    register_rate_limit: str = "5/minute"
    schema_cache_ttl_seconds: int = 600

    # ── Operator admin allowlist ──────────────────────────────────────
    # Comma-separated emails granted access to /api/v1/admin/*. Case-
    # insensitive. Empty = no admins (all admin endpoints return 403).
    admin_emails: str = ""

    # ── Onboarding gates (disabled by default; enable when Auth0/Stripe integrated) ──
    billing_gate_enabled: bool = False
    mfa_gate_enabled: bool = False

    # Stripe billing settings
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_pro_price_id: str = ""
    stripe_api_base: str = "https://api.stripe.com"
    stripe_checkout_success_url: str = ""
    stripe_checkout_cancel_url: str = ""
    stripe_customer_portal_return_url: str = ""

    # ── Verification token TTLs ────────────────────────────────────────
    email_verification_token_ttl_minutes: int = 60
    login_link_token_ttl_minutes: int = 30
    user_session_ttl_hours: int = 24

    # ── SMTP settings (optional; if smtp_host is unset, LogEmailSender is used) ──
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_address: str | None = None

    # ── Resend HTTP API (preferred over SMTP when both api_key and from_address are set) ──
    resend_api_key: str | None = None
    resend_from_address: str | None = None

    # ── Application base URL (used to build the MCP endpoint URL in setup payloads) ──
    app_base_url: str = "http://localhost:8000"

    # ── Frontend base URL (used for email verification/login link redirects) ──
    frontend_base_url: str = "http://localhost:3000"

    # ── MCP OAuth resource-server settings ────────────────────────────────────
    # Controls which auth methods are accepted on the public /mcp endpoint.
    #   api_key_only  – current behaviour; bearer API keys only
    #   hybrid        – accepts both OAuth access tokens and API keys (rollout)
    #   oauth_only    – OAuth access tokens only (production target)
    mcp_auth_mode: Literal["api_key_only", "hybrid", "oauth_only"] = "api_key_only"

    # Canonical public URL of this MCP resource server (e.g. https://app.example.com/mcp).
    # Required when mcp_auth_mode != api_key_only.
    mcp_resource_url: str = ""

    # ── OAuth provider settings (issuer = authorization server base URL) ──────
    oauth_issuer_url: str = ""  # e.g. https://YOUR_DOMAIN.auth0.com/
    oauth_audience: str = ""  # expected aud claim / resource indicator
    oauth_jwks_url: str = ""  # optional override; defaults to {issuer}/.well-known/jwks.json
    oauth_required_scopes: str = "mcp:access"  # comma-separated
    oauth_http_timeout_seconds: int = 10
    oauth_jwks_cache_seconds: int = 300

    # ── OAuth client for the account-linking flow ─────────────────────────────
    # These are only needed for the "Connect MCP account" UI flow that lets an
    # authenticated web-app user bind their local account to an OAuth identity.
    oauth_client_id: str = ""
    oauth_client_secret: str = ""  # leave empty for PKCE-only (public client)
    oauth_link_redirect_uri: str = (
        ""  # backend callback URL, e.g. https://app.example.com/api/v1/account/mcp-oauth/callback
    )

    # ── OpenTelemetry tracing (G16) ───────────────────────────────────
    otel_enabled: bool = False
    otel_service_name: str = "mcp-db-agent"
    otel_otlp_endpoint: str = "http://localhost:4317"
    otel_otlp_protocol: Literal["grpc", "http"] = "grpc"
    otel_otlp_insecure: bool = True
    otel_sampler_ratio: float = 1.0
    otel_capture_sql_text: bool = False

    @field_validator("otel_sampler_ratio")
    @classmethod
    def _clamp_otel_sampler_ratio(cls, v: float) -> float:
        if v < 0.0:
            return 0.0
        if v > 1.0:
            return 1.0
        return v

    @field_validator("credential_encryption_keys")
    @classmethod
    def _check_keys(cls, v: str, info) -> str:
        if not v and info.data.get("environment") != "development":
            raise ValueError(
                "CREDENTIAL_ENCRYPTION_KEYS is required in non-development mode. "
                'Generate one with: python -c "from cryptography.fernet import Fernet;'
                ' print(Fernet.generate_key().decode())"'
            )
        return v

    @field_validator("registration_open")
    @classmethod
    def _check_registration_open(cls, v: bool | None, info) -> bool | None:
        if v is None and info.data.get("environment") != "development":
            raise ValueError(
                "REGISTRATION_OPEN must be explicitly set (true or false) in "
                "non-development environments. Set REGISTRATION_OPEN=false to "
                "close public registration."
            )
        return v

    @model_validator(mode="after")
    def _check_oauth_audience(self) -> "Settings":
        if (
            self.mcp_auth_mode in {"hybrid", "oauth_only"}
            and not self.oauth_audience
            and self.environment != "development"
        ):
            raise ValueError(
                "OAUTH_AUDIENCE must be set when MCP_AUTH_MODE is 'hybrid' or "
                "'oauth_only' in non-development environments. "
                "Set it to the resource-server identifier registered with your "
                "authorization server (e.g. https://app.example.com/mcp)."
            )
        if self.billing_gate_enabled and not self.stripe_billing_is_configured():
            raise ValueError(
                "Stripe billing is enabled but STRIPE_SECRET_KEY, "
                "STRIPE_WEBHOOK_SECRET, and STRIPE_PRO_PRICE_ID are not all set."
            )
        return self

    def credential_encryption_keys_list(self) -> list[str]:
        return [k.strip() for k in self.credential_encryption_keys.split(",") if k.strip()]

    def admin_emails_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    def oauth_required_scopes_list(self) -> list[str]:
        return [s.strip() for s in self.oauth_required_scopes.split(",") if s.strip()]

    def effective_mcp_resource_url(self) -> str:
        """Return the canonical MCP resource URL, defaulting to app_base_url/mcp."""
        if self.mcp_resource_url:
            return self.mcp_resource_url.rstrip("/")
        return f"{self.app_base_url.rstrip('/')}/mcp"

    def oauth_is_configured(self) -> bool:
        """Return True when the minimum OAuth settings are present."""
        return bool(self.oauth_issuer_url and self.mcp_resource_url)

    def oauth_link_is_configured(self) -> bool:
        """Return True when the account-linking OAuth client is fully configured."""
        return bool(self.oauth_client_id and self.oauth_link_redirect_uri and self.oauth_issuer_url)

    def stripe_billing_is_configured(self) -> bool:
        """Return True when Stripe can create sessions and verify webhooks."""
        return bool(
            self.stripe_secret_key and self.stripe_webhook_secret and self.stripe_pro_price_id
        )

    def stripe_checkout_success_url_effective(self) -> str:
        if self.stripe_checkout_success_url:
            return self.stripe_checkout_success_url
        return f"{self.frontend_base_url.rstrip('/')}/app/billing?checkout=success"

    def stripe_checkout_cancel_url_effective(self) -> str:
        if self.stripe_checkout_cancel_url:
            return self.stripe_checkout_cancel_url
        return f"{self.frontend_base_url.rstrip('/')}/app/billing?checkout=cancelled"

    def stripe_customer_portal_return_url_effective(self) -> str:
        if self.stripe_customer_portal_return_url:
            return self.stripe_customer_portal_return_url
        return f"{self.frontend_base_url.rstrip('/')}/app/billing"

    def mcp_oauth_enabled(self) -> bool:
        """Return True when /mcp is actively accepting OAuth bearer tokens."""
        return self.mcp_auth_mode in {"hybrid", "oauth_only"} and self.oauth_is_configured()

    def mcp_api_keys_enabled(self) -> bool:
        """Return True when /mcp is actively accepting API keys."""
        return self.mcp_auth_mode in {"api_key_only", "hybrid"}


settings: Settings = Settings()
