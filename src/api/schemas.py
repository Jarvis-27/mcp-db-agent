"""Pydantic v2 request/response models for the tenant-backed REST API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(..., min_length=1, max_length=254)
    tenant_name: str | None = Field(default=None, max_length=200)


class RegistrationPendingResponse(BaseModel):
    tenant_id: str
    status: str
    message: str


class VerifyEmailResponse(BaseModel):
    tenant_id: str
    status: str
    next_step: str
    owner_session_token: str
    expires_in_seconds: int


class RequestLoginLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(..., min_length=1, max_length=254)


class GenericAcceptedResponse(BaseModel):
    message: str


class OwnerSessionResponse(BaseModel):
    tenant_id: str
    status: str
    owner_session_token: str
    expires_in_seconds: int


class SubmitDatabaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_url: str = Field(..., min_length=1, max_length=2048)
    name: str | None = Field(default="primary", max_length=100)


class OnboardingDatabaseResponse(BaseModel):
    tenant_id: str
    status: str  # onboarding progress state
    account_status: str  # account health state
    plan_code: str  # plan activated on completion
    next_step: str


class AdminStatusResponse(BaseModel):
    tenant_id: str
    status: str  # onboarding progress state
    account_status: str  # account health state


class PendingTenantItem(BaseModel):
    tenant_id: str
    owner_email: str | None
    created_at: str
    onboarding_status: str
    account_status: str


class TenantMetaResponse(BaseModel):
    tenant_id: str
    is_active: bool
    created_at: str
    status: str  # onboarding progress (backward compat)
    account_status: str
    plan_code: str
    billing_status: str


class UpdateRequest(BaseModel):
    database_url: str | None = Field(default=None, max_length=2048)


class RotateKeyResponse(BaseModel):
    api_key: str


class OnboardingStatusResponse(BaseModel):
    tenant_id: str
    status: str  # onboarding progress state
    account_status: str  # account health state
    plan_code: str
    billing_status: str
    next_step: str
    blockers: list[str]
    can_issue_api_key: bool


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
    tenant_id: str
    status: str
    account_status: str
    plan_code: str
    billing_status: str
    mcp_url: str
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
    tenant_id: str
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
    question: str
    sql: str | None
    success: bool
    row_count: int | None
    duration_ms: int | None
    error: str | None


class UsageRecentResponse(BaseModel):
    items: list[RecentQueryItem]
    total: int
