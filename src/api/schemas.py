"""Pydantic v2 request/response models for the REST API."""

from typing import Literal

from pydantic import BaseModel, Field

LLMProvider = Literal["anthropic", "groq"]


class RegisterRequest(BaseModel):
    database_url: str = Field(..., min_length=1, max_length=2048)
    llm_provider: LLMProvider = "anthropic"
    anthropic_api_key: str | None = Field(default=None, max_length=512)
    groq_api_key: str | None = Field(default=None, max_length=512)


class RegisterResponse(BaseModel):
    user_id: str
    api_key: str  # 'mdbk_...' — shown ONCE, never again
    warning: str = "Store this key now. We cannot show it to you again."


class UserMetaResponse(BaseModel):
    user_id: str
    llm_provider: LLMProvider
    has_anthropic_key: bool
    has_groq_key: bool
    is_active: bool
    created_at: str  # ISO 8601 UTC
    daily_query_count: int


class UpdateRequest(BaseModel):
    database_url: str | None = Field(default=None, max_length=2048)
    llm_provider: LLMProvider | None = None
    anthropic_api_key: str | None = Field(default=None, max_length=512)
    groq_api_key: str | None = Field(default=None, max_length=512)


class RotateKeyResponse(BaseModel):
    api_key: str  # new key, shown ONCE
