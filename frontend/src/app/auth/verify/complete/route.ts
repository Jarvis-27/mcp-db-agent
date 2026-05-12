import type { NextRequest } from 'next/server'
import { NextResponse } from 'next/server'
import {
  getApiErrorMessage,
  getBackendApiUrl,
  getRequestBaseUrl,
  redirectWithError,
  setSessionCookie,
} from '@/lib/api/auth-callback'
import { resolveOnboardingDestination } from '@/lib/onboarding'
import type { VerifyEmailResponse } from '@/types/api'

export async function GET(request: NextRequest) {
  const token = request.nextUrl.searchParams.get('token')
  const tz = request.nextUrl.searchParams.get('tz')

  if (!token) {
    return redirectWithError(request, '/auth/verify', 'This verification link is missing a token.')
  }

  const params = new URLSearchParams({ token })
  if (tz) params.set('tz', tz)
  const res = await fetch(
    `${getBackendApiUrl()}/api/v1/auth/verify-email?${params.toString()}`,
    { cache: 'no-store' },
  )

  if (!res.ok) {
    const message = await getApiErrorMessage(res, 'Email verification failed.')
    return redirectWithError(request, '/auth/verify', message)
  }

  const data: VerifyEmailResponse = await res.json()
  const destination = resolveOnboardingDestination(data.status)
  const response = NextResponse.redirect(new URL(destination, getRequestBaseUrl(request)))

  setSessionCookie(response, data.session_token, data.expires_in_seconds)

  return response
}