"""Internal typed structures for setup payload generation."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SetupQuotaSummary:
    daily_limit: int
    daily_used: int
    daily_remaining: int
    reset_at: datetime
    warning_level: str | None


@dataclass(frozen=True)
class SetupApiKeyState:
    active_key_count: int
    selected_api_key_id: str | None
    selected_api_key_name: str | None
    selected_api_key_prefix: str | None
    raw_key_included: bool
    requires_manual_key_entry: bool


@dataclass(frozen=True)
class ClientSetupPayload:
    client_id: str
    display_name: str
    status: str
    auth_method: str
    config_path_hint: str
    snippet_format: str
    snippet: str
    api_key_handling: str
    instructions: tuple[str, ...]
    availability_reason: str | None = None


@dataclass(frozen=True)
class SetupPayload:
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
    quota_summary: SetupQuotaSummary
    api_key_state: SetupApiKeyState
    sample_prompts: tuple[str, ...]
    vs_code: ClientSetupPayload
    cursor: ClientSetupPayload
    chatgpt_developer_mode: ClientSetupPayload
    claude_desktop: ClientSetupPayload
    generic_http: ClientSetupPayload
