import type {
  AccountStatus,
  OnboardingBlocker,
  OnboardingStatus,
  OnboardingStatusResponse,
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
    case 'pending_billing':
    case 'pending_mfa':
    case 'pending_review':
    default:
      return '/setup/status'
  }
}

export function resolveStatusResponseDestination(
  payload: Pick<OnboardingStatusResponse, 'status' | 'account_status'>,
): ProtectedRoute {
  return resolveOnboardingDestination(payload.status, payload.account_status)
}

export function getStatusPageCopy(
  status: OnboardingStatus,
  accountStatus: AccountStatus,
  blockers: OnboardingBlocker[],
): { title: string; detail: string } {
  if (accountStatus === 'restricted' || blockers.includes('account_restricted')) {
    return {
      title: 'Account restricted',
      detail: 'Your account is temporarily restricted. Review the message below and contact support if you need help.',
    }
  }

  if (accountStatus === 'suspended' || blockers.includes('account_suspended')) {
    return {
      title: 'Account suspended',
      detail: 'Your account is suspended. You will not be able to continue setup until the restriction is cleared.',
    }
  }

  if (accountStatus === 'closed' || blockers.includes('account_closed')) {
    return {
      title: 'Account closed',
      detail: 'This tenant has been closed. Setup and API-key management are no longer available for this account.',
    }
  }

  if (status === 'pending_billing' || blockers.includes('billing')) {
    return {
      title: 'Billing setup required',
      detail: 'Billing is enabled for this environment. Finish the required billing step before continuing with database setup.',
    }
  }

  if (status === 'pending_mfa' || blockers.includes('mfa')) {
    return {
      title: 'Additional verification required',
      detail: 'This environment requires MFA before database setup can continue.',
    }
  }

  if (status === 'pending_review' || blockers.includes('admin_review')) {
    return {
      title: 'Account under review',
      detail: 'Your account is waiting for manual review. Setup will resume automatically after the hold is cleared.',
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
