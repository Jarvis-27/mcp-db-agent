import type { NextRequest } from 'next/server'
import { NextResponse } from 'next/server'
import {
  getApiErrorMessage,
  getBackendApiUrl,
  getRequestBaseUrl,
  redirectWithError,
  setOwnerSessionCookie,
} from '@/lib/api/auth-callback'
import { resolveOnboardingDestination } from '@/lib/onboarding'
import type { VerifyEmailResponse } from '@/types/api'

export async function GET(request: NextRequest) {
  const token = request.nextUrl.searchParams.get('token')

  if (!token) {
    return redirectWithError(request, '/auth/verify', 'This verification link is missing a token.')
  }

  const res = await fetch(
    `${getBackendApiUrl()}/api/v1/onboarding/verify-email?token=${encodeURIComponent(token)}`,
    { cache: 'no-store' },
  )

  if (!res.ok) {
    const message = await getApiErrorMessage(res, 'Email verification failed.')
    return redirectWithError(request, '/auth/verify', message)
  }

  const data: VerifyEmailResponse = await res.json()
  const destination = resolveOnboardingDestination(data.status)
  const response = NextResponse.redirect(new URL(destination, getRequestBaseUrl(request)))

  setOwnerSessionCookie(response, data.owner_session_token, data.expires_in_seconds)

  return response
}
