"""Pydantic v2 request/response models for the tenant-backed REST API."""

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
    status: str
    next_step: str


class AdminStatusResponse(BaseModel):
    tenant_id: str
    status: str


class PendingTenantItem(BaseModel):
    tenant_id: str
    owner_email: str | None
    created_at: str
    onboarding_status: str


class TenantMetaResponse(BaseModel):
    tenant_id: str
    is_active: bool
    created_at: str
    status: str


class UpdateRequest(BaseModel):
    database_url: str | None = Field(default=None, max_length=2048)


class RotateKeyResponse(BaseModel):
    api_key: str


class OnboardingStatusResponse(BaseModel):
    tenant_id: str
    status: str
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
