"""Setup payload orchestration for customer-facing client configuration."""

from dataclasses import dataclass
from datetime import UTC, datetime

from src.auth.onboarding import ACCOUNT_ACTIVE, SETUP_COMPLETE
from src.auth.user_store import ApiKey, User, UserStore
from src.entitlements.service import EntitlementService
from src.setup.config_templates import (
    build_chatgpt_payload,
    build_cursor_payload,
    build_generic_http_payload,
    build_vs_code_payload,
)
from src.setup.schemas import SetupApiKeyState, SetupPayload, SetupQuotaSummary

_SAMPLE_PROMPTS = (
    "List the tables in this database.",
    "Describe the schema for the orders table.",
    "What were the top 10 customers by revenue last month?",
)


class SetupPayloadInputError(ValueError):
    """Raised when the caller supplies invalid setup payload input."""


class SetupPayloadEligibilityError(ValueError):
    """Raised when the user is not eligible to receive setup payloads."""


@dataclass(frozen=True)
class _SelectedApiKey:
    api_key: ApiKey | None
    raw_key: str | None


class SetupPayloadService:
    def __init__(
        self,
        user_store: UserStore,
        *,
        app_base_url: str,
        mcp_auth_mode: str = "api_key_only",
        oauth_configured: bool = False,
        oauth_link_configured: bool = False,
        entitlements: EntitlementService | None = None,
    ) -> None:
        self._user_store = user_store
        self._app_base_url = app_base_url.rstrip("/")
        self._mcp_auth_mode = mcp_auth_mode
        self._oauth_configured = oauth_configured
        self._oauth_link_configured = oauth_link_configured
        self._entitlements = entitlements or EntitlementService()

    def build_payload(self, user_id: str, *, raw_api_key: str | None = None) -> SetupPayload:
        user = self._user_store.get_user_row(user_id)
        if user is None:
            raise LookupError(f"User {user_id} not found")
        self._ensure_eligible(user)

        selected_key = self._select_api_key(user_id, raw_api_key=raw_api_key)
        active_key_count = self._user_store.count_active_api_keys(user_id)
        plan = self._entitlements.get_plan(str(user.plan_code))
        daily_used = int(user.daily_query_count)
        quota_summary = SetupQuotaSummary(
            daily_limit=plan.ask_database_per_day,
            daily_used=daily_used,
            daily_remaining=max(plan.ask_database_per_day - daily_used, 0),
            reset_at=_ensure_utc(user.daily_quota_reset_at),
            warning_level=self._entitlements.quota_warning_level(str(user.plan_code), daily_used),
        )
        key_state = SetupApiKeyState(
            active_key_count=active_key_count,
            selected_api_key_id=None
            if selected_key.api_key is None
            else str(selected_key.api_key.id),
            selected_api_key_name=(
                None if selected_key.api_key is None else str(selected_key.api_key.name)
            ),
            selected_api_key_prefix=(
                None if selected_key.api_key is None else str(selected_key.api_key.prefix)
            ),
            raw_key_included=selected_key.raw_key is not None,
            requires_manual_key_entry=selected_key.raw_key is None,
        )
        mcp_url = f"{self._app_base_url}/mcp"
        raw_key = selected_key.raw_key
        oauth_enabled_for_mcp = self._oauth_configured and self._mcp_auth_mode in {
            "hybrid",
            "oauth_only",
        }
        api_keys_enabled_for_mcp = self._mcp_auth_mode in {"api_key_only", "hybrid"}
        return SetupPayload(
            user_id=user_id,
            status=str(user.onboarding_status),
            account_status=str(user.account_status),
            plan_code=str(user.plan_code),
            billing_status=str(user.billing_status),
            mcp_url=mcp_url,
            mcp_auth_mode=self._mcp_auth_mode,
            oauth_enabled_for_mcp=oauth_enabled_for_mcp,
            oauth_link_enabled=self._oauth_link_configured,
            api_keys_enabled_for_mcp=api_keys_enabled_for_mcp,
            quota_summary=quota_summary,
            api_key_state=key_state,
            sample_prompts=_SAMPLE_PROMPTS,
            vs_code=build_vs_code_payload(
                mcp_url,
                raw_key,
                oauth_configured=oauth_enabled_for_mcp,
                api_keys_enabled=api_keys_enabled_for_mcp,
            ),
            cursor=build_cursor_payload(
                mcp_url,
                raw_key,
                oauth_configured=oauth_enabled_for_mcp,
                api_keys_enabled=api_keys_enabled_for_mcp,
            ),
            chatgpt_developer_mode=build_chatgpt_payload(
                mcp_url,
                oauth_configured=oauth_enabled_for_mcp,
            ),
            generic_http=build_generic_http_payload(
                mcp_url,
                raw_key,
                oauth_configured=oauth_enabled_for_mcp,
                api_keys_enabled=api_keys_enabled_for_mcp,
            ),
        )

    def _ensure_eligible(self, user: User) -> None:
        if str(user.account_status) != ACCOUNT_ACTIVE:
            raise SetupPayloadEligibilityError(
                "Account must be active before requesting setup payloads."
            )
        if str(user.onboarding_status) != SETUP_COMPLETE:
            raise SetupPayloadEligibilityError(
                "Account setup must be complete before requesting setup payloads."
            )
        if user.db_url_enc is None:
            raise SetupPayloadEligibilityError(
                "Account must have an active database before requesting setup payloads."
            )

    def _select_api_key(self, user_id: str, *, raw_api_key: str | None) -> _SelectedApiKey:
        normalized = None if raw_api_key is None else raw_api_key.strip()
        if normalized:
            api_key = self._user_store.get_active_api_key_for_user_by_raw_key(
                user_id,
                normalized,
            )
            if api_key is None:
                raise SetupPayloadInputError(
                    "Provided raw_api_key does not match an active API key for this account."
                )
            return _SelectedApiKey(api_key=api_key, raw_key=normalized)

        active_key = next(
            (row for row in self._user_store.list_api_keys(user_id) if row.revoked_at is None),
            None,
        )
        return _SelectedApiKey(api_key=active_key, raw_key=None)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt
