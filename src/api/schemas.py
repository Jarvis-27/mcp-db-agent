"""Pydantic v2 request/response models for the user-account REST API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(..., min_length=1, max_length=254)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)


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
    timezone: str | None = Field(default=None, min_length=1, max_length=64)


class GenericAcceptedResponse(BaseModel):
    message: str


class SessionResponse(BaseModel):
    user_id: str
    status: str
    session_token: str
    expires_in_seconds: int


class SubmitDatabaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_method: Literal["guided", "url"] | None = None
    database_url: str | None = Field(default=None, min_length=1, max_length=2048)
    provider: (
        Literal[
            "generic_postgres",
            "supabase",
            "neon",
            "aws_rds",
            "railway",
            "render",
        ]
        | None
    ) = None
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=5432, ge=1, le=65535)
    database: str | None = Field(default=None, min_length=1, max_length=255)
    username: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=1, max_length=512)
    sslmode: Literal["require", "verify-ca", "verify-full"] = "require"
    name: str | None = Field(default="primary", max_length=100)


class DatabaseResponse(BaseModel):
    user_id: str
    status: str  # onboarding progress state
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
    status: str  # onboarding progress state
    account_status: str
    plan_code: str
    billing_status: str
    next_step: str
    blockers: list[str]
    can_issue_api_key: bool
    static_outbound_ip: str | None = None


class AccountResponse(BaseModel):
    user_id: str
    is_active: bool
    created_at: str
    status: str  # onboarding progress
    account_status: str
    plan_code: str
    billing_status: str
    timezone: str


class UpdatePreferencesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(..., min_length=1, max_length=64)


class PreferencesResponse(BaseModel):
    user_id: str
    timezone: str
    daily_quota_reset_at: datetime


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


class BillingSummaryResponse(BaseModel):
    user_id: str
    plan_code: str
    plan_display_name: str
    billing_status: str
    daily_limit: int
    daily_used: int
    daily_remaining: int
    checkout_available: bool
    portal_available: bool
    stripe_customer_configured: bool
    billing_current_period_end: str | None


class BillingSessionResponse(BaseModel):
    id: str
    url: str


class BillingWebhookResponse(BaseModel):
    received: bool
    processed: bool
    duplicate: bool
    event_id: str
    event_type: str
    user_id: str | None = None
    billing_status: str | None = None
    plan_code: str | None = None


class BillingConfirmRequest(BaseModel):
    session_id: str


class BillingConfirmResponse(BaseModel):
    processed: bool
    already_pro: bool
    not_paid: bool
    summary: BillingSummaryResponse


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


# ── Admin schemas ─────────────────────────────────────────────────────


class AdminGrant(BaseModel):
    scope: str  # currently always "operator"


class AdminMeResponse(BaseModel):
    user_id: str
    email: str
    is_admin: bool
    grants: list[AdminGrant]


class AdminUserCountsByStatus(BaseModel):
    active: int
    suspended: int
    closed: int
    pending_email_verification: int


class AdminQueryDailyCount(BaseModel):
    date: str  # YYYY-MM-DD
    total: int
    errors: int


class AdminOverviewResponse(BaseModel):
    users_total: int
    users_active_7d: int
    users_by_status: AdminUserCountsByStatus
    queries_today: int
    error_rate_today: float  # 0.0 — 1.0
    p50_duration_ms_today: int | None
    p95_duration_ms_today: int | None
    daily_query_counts: list[AdminQueryDailyCount]  # last 14 days


class AdminUserListItem(BaseModel):
    user_id: str
    email: str
    plan_code: str
    account_status: str
    onboarding_status: str
    daily_query_count: int
    daily_quota_reset_at: str
    created_at: str
    last_query_at: str | None


class AdminUsersListResponse(BaseModel):
    items: list[AdminUserListItem]
    total: int
    limit: int
    offset: int


class AdminApiKeySummary(BaseModel):
    id: str
    name: str
    prefix: str
    scopes: list[str]
    created_at: str
    last_used_at: str | None
    revoked_at: str | None


class AdminUserDetailResponse(BaseModel):
    user_id: str
    email: str
    plan_code: str
    billing_status: str
    account_status: str
    onboarding_status: str
    timezone: str
    created_at: str
    updated_at: str
    email_verified_at: str | None
    suspended_at: str | None
    closed_at: str | None
    db_name: str | None
    db_validation_status: str | None
    db_last_validation_at: str | None
    daily_query_count: int
    daily_quota_reset_at: str
    api_keys: list[AdminApiKeySummary]
    recent_queries: list[RecentQueryItem]


class AdminSuspendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class AdminUserActionResponse(BaseModel):
    user_id: str
    account_status: str
    suspended_at: str | None
    closed_at: str | None


class AdminQueryListItem(BaseModel):
    id: int
    timestamp: str
    user_id: str
    user_email: str | None
    api_key_id: str | None
    question: str
    sql: str | None
    success: bool
    row_count: int | None
    duration_ms: int | None
    error: str | None
    error_code: str | None
    attempts: int


class AdminQueryListResponse(BaseModel):
    items: list[AdminQueryListItem]
    total: int
    limit: int
    offset: int
