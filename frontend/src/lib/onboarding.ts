import type {
  AccountStatus,
  AccountStatusResponse,
  OnboardingBlocker,
  OnboardingStatus,
} from '@/types/api'

export type ProtectedRoute = '/api-keys' | '/setup/api-key' | '/setup/clients' | '/setup/database' | '/setup/status'

export function resolveOnboardingDestination(
  status: OnboardingStatus,
  accountStatus: AccountStatus = 'active',
): ProtectedRoute {
  if (accountStatus !== 'active') {
    return '/setup/status'
  }

  switch (status) {
    case 'setup_complete':
      return '/setup/clients'
    case 'pending_db_connection':
      return '/setup/database'
    case 'pending_email_verification':
    default:
      return '/setup/status'
  }
}

export function resolveStatusResponseDestination(
  payload: Pick<AccountStatusResponse, 'status' | 'account_status'>,
): ProtectedRoute {
  return resolveOnboardingDestination(payload.status, payload.account_status)
}

export function getStatusPageCopy(
  status: OnboardingStatus,
  accountStatus: AccountStatus,
  blockers: OnboardingBlocker[],
): { title: string; detail: string } {
  if (accountStatus === 'suspended' || blockers.includes('account_suspended')) {
    return {
      title: 'Account suspended',
      detail: 'Your account is suspended. You will not be able to continue setup until the restriction is cleared.',
    }
  }

  if (accountStatus === 'closed' || blockers.includes('account_closed')) {
    return {
      title: 'Account closed',
      detail: 'This account has been closed. Setup and API-key management are no longer available.',
    }
  }

  if (status === 'pending_email_verification' || blockers.includes('email_verification')) {
    return {
      title: 'Email verification required',
      detail: 'Your email address must be verified before setup can continue.',
    }
  }

  return {
    title: 'Setup unavailable',
    detail: 'This account cannot continue setup from the current state.',
  }
}