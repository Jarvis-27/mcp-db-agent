"""Pydantic v2 request/response models for the REST API."""

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=1, max_length=254)
    database_url: str = Field(..., min_length=1, max_length=2048)


class RegistrationPendingResponse(BaseModel):
    user_id: str
    status: str   # "pending_email_verification"
    message: str  # human-readable next step


class RegisterResponse(BaseModel):
    """Kept for backward compatibility with existing tests."""

    user_id: str
    api_key: str  # 'mdbk_...' — shown ONCE, never again
    warning: str = "Store this key now. We cannot show it to you again."


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
