"""Pydantic v2 request/response models for the user-account REST API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(..., min_length=1, max_length=254)


class SignupPendingResponse(BaseModel):
    user_id: str
    status: str
    message: str


class VerifyEmailResponse(BaseModel):
    user_id: str
    status: str
    next_step: str
    session_token: str
    expires_in_seconds: int


class RequestLoginLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(..., min_length=1, max_length=254)


class GenericAcceptedResponse(BaseModel):
    message: str


class SessionResponse(BaseModel):
    user_id: str
    status: str
    session_token: str
    expires_in_seconds: int


class SubmitDatabaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_url: str = Field(..., min_length=1, max_length=2048)
    name: str | None = Field(default="primary", max_length=100)


class DatabaseResponse(BaseModel):
    user_id: str
    status: str        # onboarding progress state
    account_status: str
    plan_code: str
    next_step: str


class DatabaseMetadataResponse(BaseModel):
    name: str
    db_type: str | None
    connected: bool
    host: str | None
    database_name: str | None
    last_validated_at: str | None


class AccountStatusResponse(BaseModel):
    user_id: str
    status: str        # onboarding progress state
    account_status: str
    plan_code: str
    billing_status: str
    next_step: str
    blockers: list[str]
    can_issue_api_key: bool


class AccountResponse(BaseModel):
    user_id: str
    is_active: bool
    created_at: str
    status: str        # onboarding progress
    account_status: str
    plan_code: str
    billing_status: str


class CreateApiKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="default", min_length=1, max_length=100)
    scopes: list[str] = Field(default_factory=lambda: ["mcp_read"])


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    prefix: str
    scopes: list[str]
    created_at: str
    last_used_at: str | None
    revoked_at: str | None


class CreatedApiKeyResponse(ApiKeyResponse):
    api_key: str
    warning: str = "Store this key now. We cannot show it to you again."


class RotateKeyResponse(BaseModel):
    api_key: str


class SetupPayloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_api_key: str | None = Field(default=None, min_length=1, max_length=512)


class SetupQuotaSummaryResponse(BaseModel):
    daily_limit: int
    daily_used: int
    daily_remaining: int
    reset_at: str
    warning_level: str | None


class SetupApiKeyStateResponse(BaseModel):
    active_key_count: int
    selected_api_key_id: str | None
    selected_api_key_name: str | None
    selected_api_key_prefix: str | None
    raw_key_included: bool
    requires_manual_key_entry: bool


class ClientSetupPayloadResponse(BaseModel):
    client_id: str
    display_name: str
    status: str
    auth_method: str
    config_path_hint: str
    snippet_format: str
    snippet: str
    api_key_handling: str
    instructions: list[str]
    availability_reason: str | None = None


class SetupClientsResponse(BaseModel):
    vs_code: ClientSetupPayloadResponse
    cursor: ClientSetupPayloadResponse
    chatgpt_developer_mode: ClientSetupPayloadResponse
    generic_http: ClientSetupPayloadResponse


class SetupPayloadResponse(BaseModel):
    user_id: str
    status: str
    account_status: str
    plan_code: str
    billing_status: str
    mcp_url: str
    mcp_auth_mode: str
    oauth_enabled_for_mcp: bool
    oauth_link_enabled: bool
    api_keys_enabled_for_mcp: bool
    quota_summary: SetupQuotaSummaryResponse
    api_key_state: SetupApiKeyStateResponse
    sample_prompts: list[str]
    clients: SetupClientsResponse


# ── Dashboard / usage summary schemas ────────────────────────────────────────


class ActiveDatabaseSummary(BaseModel):
    name: str
    validation_status: str


class QuotaSummary(BaseModel):
    daily_limit: int
    daily_used: int
    daily_remaining: int
    reset_at: datetime
    warning_level: str | None


class DashboardSummaryResponse(BaseModel):
    user_id: str
    account_status: str
    onboarding_status: str
    plan_code: str
    billing_status: str
    active_database: ActiveDatabaseSummary | None
    api_key_count: int
    quota: QuotaSummary


class RecentQueryItem(BaseModel):
    id: int
    timestamp: str
    created_at: str
    question: str
    sql: str | None
    success: bool
    row_count: int | None
    duration_ms: int | None
    error: str | None
    attempts: int
    warning_level: str | None
    api_key_id: str | None
    api_key_name: str | None = None


class UsageRecentResponse(BaseModel):
    items: list[RecentQueryItem]
    total: int


# ── OAuth MCP account-linking schemas ─────────────────────────────────────────


class OAuthLinkStartResponse(BaseModel):
    """Returned by the start endpoint; the frontend must redirect to authorization_url."""

    authorization_url: str
    state: str  # opaque value; included here for debugging only


class OAuthLinkStatusResponse(BaseModel):
    """Current OAuth linkage state for the authenticated user."""

    linked: bool
    issuer: str | None = None
    oauth_email: str | None = None
    oauth_last_login_at: str | None = None  # ISO-8601


class OAuthUnlinkResponse(BaseModel):
    message: str
