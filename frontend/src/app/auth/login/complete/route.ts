import type { NextRequest } from 'next/server'
import { NextResponse } from 'next/server'
import {
  getApiErrorMessage,
  getBackendApiUrl,
  redirectWithError,
  setOwnerSessionCookie,
} from '@/lib/api/auth-callback'
import { resolveStatusResponseDestination } from '@/lib/onboarding'
import type { OnboardingStatusResponse, OwnerSessionResponse } from '@/types/api'

export async function GET(request: NextRequest) {
  const token = request.nextUrl.searchParams.get('token')

  if (!token) {
    return redirectWithError(request, '/auth/login', 'This sign-in link is missing a token.')
  }

  const backendUrl = getBackendApiUrl()
  const res = await fetch(
    `${backendUrl}/api/v1/auth/exchange-login-link?token=${encodeURIComponent(token)}`,
    { cache: 'no-store' },
  )

  if (!res.ok) {
    const message = await getApiErrorMessage(res, 'Sign-in failed.')
    return redirectWithError(request, '/auth/login', message)
  }

  const data: OwnerSessionResponse = await res.json()
  let destination = '/setup/status'

  const statusRes = await fetch(`${backendUrl}/api/v1/onboarding/status`, {
    headers: { 'x-owner-session': data.owner_session_token },
    cache: 'no-store',
  })

  if (statusRes.ok) {
    const status: OnboardingStatusResponse = await statusRes.json()
    destination = resolveStatusResponseDestination(status)
  }

  const response = NextResponse.redirect(new URL(destination, request.url))
  setOwnerSessionCookie(response, data.owner_session_token, data.expires_in_seconds)

  return response
}
