import type { NextRequest } from 'next/server'
import { NextResponse } from 'next/server'
import {
  getApiErrorMessage,
  getBackendApiUrl,
  getRequestBaseUrl,
  redirectWithError,
  setSessionCookie,
} from '@/lib/api/auth-callback'
import { resolveStatusResponseDestination } from '@/lib/onboarding'
import type { AccountStatusResponse, SessionResponse } from '@/types/api'

export async function GET(request: NextRequest) {
  const token = request.nextUrl.searchParams.get('token')
  const tz = request.nextUrl.searchParams.get('tz')

  if (!token) {
    return redirectWithError(request, '/auth/login', 'This sign-in link is missing a token.')
  }

  const backendUrl = getBackendApiUrl()
  const params = new URLSearchParams({ token })
  if (tz) params.set('tz', tz)
  const res = await fetch(
    `${backendUrl}/api/v1/auth/exchange-login-link?${params.toString()}`,
    { cache: 'no-store' },
  )

  if (!res.ok) {
    const message = await getApiErrorMessage(res, 'Sign-in failed.')
    return redirectWithError(request, '/auth/login', message)
  }

  const data: SessionResponse = await res.json()
  let destination = '/setup/status'

  const statusRes = await fetch(`${backendUrl}/api/v1/account/status`, {
    headers: { 'x-session-token': data.session_token },
    cache: 'no-store',
  })

  if (statusRes.ok) {
    const status: AccountStatusResponse = await statusRes.json()
    destination = resolveStatusResponseDestination(status)
  }

  const response = NextResponse.redirect(new URL(destination, getRequestBaseUrl(request)))
  setSessionCookie(response, data.session_token, data.expires_in_seconds)

  return response
}