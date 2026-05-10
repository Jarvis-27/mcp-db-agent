export type OnboardingStatus =
  | 'pending_email_verification'
  | 'pending_db_connection'
  | 'setup_complete'

export type AccountStatus = 'active' | 'suspended' | 'closed'

export type OnboardingBlocker =
  | 'email_verification'
  | 'database_connection'
  | 'account_suspended'
  | 'account_closed'

/**
 * TypeScript types matching the Python backend's Pydantic response schemas.
 * Keep in sync with src/api/schemas.py.
 */

export interface SignupPendingResponse {
  user_id: string
  status: string
  message: string
}

export interface VerifyEmailResponse {
  user_id: string
  status: OnboardingStatus
  next_step: string
  session_token: string
  expires_in_seconds: number
}

export interface SessionResponse {
  user_id: string
  status: OnboardingStatus
  session_token: string
  expires_in_seconds: number
}

export interface AccountStatusResponse {
  user_id: string
  status: OnboardingStatus
  account_status: AccountStatus
  plan_code: string
  billing_status: string
  next_step: string
  blockers: OnboardingBlocker[]
  can_issue_api_key: boolean
}

export interface AccountDatabaseResponse {
  user_id: string
  status: OnboardingStatus
  account_status: AccountStatus
  plan_code: string
  next_step: string
}

export interface DatabaseMetadataResponse {
  name: string
  db_type: string | null
  connected: boolean
  host: string | null
  database_name: string | null
  last_validated_at: string | null
}

export interface CreatedApiKeyResponse {
  id: string
  name: string
  prefix: string
  scopes: string[]
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
  api_key: string
  warning: string
}

export interface ApiKeyResponse {
  id: string
  name: string
  prefix: string
  scopes: string[]
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
}

export interface ClientSetupPayloadResponse {
  client_id: string
  display_name: string
  status: string
  auth_method: string
  config_path_hint: string
  snippet_format: string
  snippet: string
  api_key_handling: string
  instructions: string[]
  availability_reason: string | null
}

export interface SetupQuotaSummaryResponse {
  daily_limit: number
  daily_used: number
  daily_remaining: number
  reset_at: string
  warning_level: string | null
}

export interface SetupPayloadResponse {
  user_id: string
  status: OnboardingStatus
  account_status: AccountStatus
  plan_code: string
  billing_status: string
  mcp_url: string
  mcp_auth_mode: 'api_key_only' | 'hybrid' | 'oauth_only'
  oauth_enabled_for_mcp: boolean
  oauth_link_enabled: boolean
  api_keys_enabled_for_mcp: boolean
  quota_summary: SetupQuotaSummaryResponse
  api_key_state: {
    active_key_count: number
    selected_api_key_id: string | null
    selected_api_key_name: string | null
    selected_api_key_prefix: string | null
    raw_key_included: boolean
    requires_manual_key_entry: boolean
  }
  sample_prompts: string[]
  clients: {
    vs_code: ClientSetupPayloadResponse
    cursor: ClientSetupPayloadResponse
    chatgpt_developer_mode: ClientSetupPayloadResponse
    generic_http: ClientSetupPayloadResponse
  }
}

export interface OAuthLinkStatusResponse {
  linked: boolean
  issuer: string | null
  oauth_email: string | null
  oauth_last_login_at: string | null
}

export interface RecentQueryItem {
  id: number
  timestamp: string
  created_at: string
  question: string
  sql: string | null
  success: boolean
  row_count: number | null
  duration_ms: number | null
  error: string | null
  attempts: number
  warning_level: string | null
  api_key_id: string | null
  api_key_name: string | null
}

export interface RecentQueriesResponse {
  items: RecentQueryItem[]
  total: number
}

export interface BillingSummaryResponse {
  user_id: string
  plan_code: string
  plan_display_name: string
  billing_status: string
  daily_limit: number
  daily_used: number
  daily_remaining: number
  checkout_available: boolean
  portal_available: boolean
  stripe_customer_configured: boolean
  billing_current_period_end: string | null
}

export interface BillingSessionResponse {
  id: string
  url: string
}

export interface ApiError {
  detail: string
}
