export type OnboardingStatus =
  | 'pending_email_verification'
  | 'pending_db_connection'
  | 'setup_complete'
  | 'pending_billing'
  | 'pending_mfa'
  | 'pending_review'

export type AccountStatus = 'active' | 'restricted' | 'suspended' | 'closed'

export type OnboardingBlocker =
  | 'email_verification'
  | 'billing'
  | 'mfa'
  | 'database_connection'
  | 'admin_review'
  | 'account_suspended'
  | 'account_closed'
  | 'account_restricted'

/**
 * TypeScript types matching the Python backend's Pydantic response schemas.
 * Keep in sync with src/api/schemas.py.
 */

export interface RegistrationPendingResponse {
  tenant_id: string
  status: string
  message: string
}

export interface VerifyEmailResponse {
  tenant_id: string
  status: OnboardingStatus
  next_step: string
  owner_session_token: string
  expires_in_seconds: number
}

export interface OwnerSessionResponse {
  tenant_id: string
  status: OnboardingStatus
  owner_session_token: string
  expires_in_seconds: number
}

export interface OnboardingStatusResponse {
  tenant_id: string
  status: OnboardingStatus
  account_status: AccountStatus
  plan_code: string
  billing_status: string
  next_step: string
  blockers: OnboardingBlocker[]
  can_issue_api_key: boolean
}

export interface OnboardingDatabaseResponse {
  tenant_id: string
  status: OnboardingStatus
  account_status: AccountStatus
  plan_code: string
  next_step: string
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
  tenant_id: string
  status: OnboardingStatus
  account_status: AccountStatus
  plan_code: string
  billing_status: string
  mcp_url: string
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

export interface ApiError {
  detail: string
}
