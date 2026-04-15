import type { NextRequest } from 'next/server'
import { NextResponse } from 'next/server'

export function getBackendApiUrl(): string {
  return process.env.BACKEND_API_URL ?? 'http://localhost:8000'
}

/**
 * Returns the public base URL (scheme + host) for building redirect URLs in
 * route handlers that run behind a reverse proxy (e.g. nginx + certbot).
 *
 * nginx rewrites the Host to "localhost:3000" internally, but it also sets
 * X-Forwarded-Proto and preserves the original Host header. Reading those
 * headers lets us produce the correct public URL instead of
 * "https://localhost:3000/...".
 */
export function getRequestBaseUrl(request: NextRequest): string {
  const parsed = new URL(request.url)
  const proto =
    request.headers.get('x-forwarded-proto') ?? parsed.protocol.replace(':', '')
  const host =
    request.headers.get('x-forwarded-host') ??
    request.headers.get('host') ??
    parsed.host
  return `${proto}://${host}`
}

export async function getApiErrorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const err = await res.json()
    if (typeof err.detail === 'string' && err.detail.trim().length > 0) {
      return err.detail
    }
  } catch {
    // Ignore invalid JSON and fall back to the default message.
  }

  return fallback
}

export function redirectWithError(
  request: NextRequest,
  pathname: '/auth/login' | '/auth/verify',
  message: string,
): NextResponse {
  const url = new URL(pathname, getRequestBaseUrl(request))
  url.searchParams.set('error', message)
  return NextResponse.redirect(url)
}

export function setSessionCookie(
  response: NextResponse,
  sessionToken: string,
  expiresInSeconds: number,
): void {
  response.cookies.set('mdb_session', sessionToken, {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    maxAge: expiresInSeconds,
    path: '/',
  })
}