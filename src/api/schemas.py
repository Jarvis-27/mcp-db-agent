"""Pydantic v2 request/response models for the REST API."""

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(..., min_length=1, max_length=254)


class RegistrationPendingResponse(BaseModel):
    user_id: str
    status: str   # "pending_email_verification"
    message: str  # human-readable next step


class VerifyEmailResponse(BaseModel):
    user_id: str
    status: str
    next_step: str
    setup_token: str  # mdbks_... — use for subsequent onboarding steps


class SubmitDatabaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    setup_token: str = Field(..., min_length=1)
    database_url: str = Field(..., min_length=1, max_length=2048)


class OnboardingDatabaseResponse(BaseModel):
    user_id: str
    status: str
    next_step: str


class AdminApproveResponse(BaseModel):
    user_id: str
    status: str
    api_key: str
    warning: str = "Store this key now. We cannot show it to you again."


class AdminStatusResponse(BaseModel):
    user_id: str
    status: str


class PendingUserItem(BaseModel):
    user_id: str
    email: str | None
    created_at: str
    onboarding_status: str


class UserMetaResponse(BaseModel):
    user_id: str
    is_active: bool
    created_at: str  # ISO 8601 UTC


class UpdateRequest(BaseModel):
    database_url: str | None = Field(default=None, max_length=2048)


class RotateKeyResponse(BaseModel):
    api_key: str  # new key, shown ONCE


class OnboardingStatusResponse(BaseModel):
    user_id: str
    status: str
    next_step: str  # what the user must do next
