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


_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE))

    # ── Single-user / stdio mode (now optional) ────────────────────────
    database_url: str = ""
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    llm_provider: str = ""
    claude_model: str = "claude-sonnet-4-6"
    groq_model: str = "llama-3.3-70b-versatile"
    max_query_rows: int = 100
    query_timeout_seconds: int = 30
    max_self_correction_retries: int = 3
    transport: str = "stdio"

    # ── Multi-tenant / hosted mode ─────────────────────────────────────
    environment: Literal["development", "staging", "production"] = "development"
    auth_database_url: str = "sqlite:///./auth.db"
    credential_encryption_keys: str = ""  # comma-separated; first is the encryption key
    registration_open: bool | None = None  # None = not explicitly set → treated as False
    allow_sqlite_user_dbs: bool = False  # NEVER true in prod
    sqlite_user_db_dir: str = "/var/lib/mcp-db-agent/user-dbs"
    extra_blocked_cidrs: str = ""  # comma-separated; e.g. "10.20.30.0/24,..."
    trusted_proxy_ips: str = "127.0.0.1"  # passed to uvicorn forwarded_allow_ips
    port: int = 8000
    cors_allow_origins: list[str] = []  # empty = closed
    max_request_bytes: int = 65536
    query_pool_size: int = 64  # ThreadPoolExecutor for SQLExecutor
    register_rate_limit: str = "5/minute"
    ask_database_quota_per_day: int = 200  # legacy fallback; hosted mode uses tenant plans
    schema_cache_ttl_seconds: int = 600

    # ── Onboarding gates (disabled by default; enable when Auth0/Stripe integrated) ──
    billing_gate_enabled: bool = False
    mfa_gate_enabled: bool = False

    # ── Admin key (required in non-development) ────────────────────────
    admin_api_key: str | None = None

    # ── Verification token TTLs ────────────────────────────────────────
    email_verification_token_ttl_minutes: int = 60
    login_link_token_ttl_minutes: int = 30
    owner_session_ttl_hours: int = 24

    # ── SMTP settings (optional; if smtp_host is unset, LogEmailSender is used) ──
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_address: str | None = None

    # ── Application base URL (used to build the MCP endpoint URL in setup payloads) ──
    app_base_url: str = "http://localhost:8000"

    # ── Frontend base URL (used for email verification/login link redirects) ──
    frontend_base_url: str = "http://localhost:3000"

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
    def _check_admin_api_key(self) -> "Settings":
        if self.environment != "development" and not self.admin_api_key:
            raise ValueError(
                "ADMIN_API_KEY must be set in non-development environments. "
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        return self

    def credential_encryption_keys_list(self) -> list[str]:
        return [k.strip() for k in self.credential_encryption_keys.split(",") if k.strip()]


settings: Settings = Settings()
